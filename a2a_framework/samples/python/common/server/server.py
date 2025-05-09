import json
import logging
from collections import defaultdict # Added for message queues
from collections.abc import AsyncIterable
from typing import Any

from pydantic import ValidationError
from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from common.server.task_manager import TaskManager
from common.types import (
    A2ARequest,
    AgentCard, # Used for validation
    CancelTaskRequest,
    GetTaskPushNotificationRequest,
    GetTaskRequest,
    InternalError,
    InvalidRequestError,
    JSONParseError,
    JSONRPCResponse,
    SendTaskRequest,
    SendTaskStreamingRequest,
    SetTaskPushNotificationRequest,
    TaskResubscriptionRequest,
)


logger = logging.getLogger(__name__)


class A2AServer:
    def __init__(
        self,
        host='0.0.0.0',
        port=5000,
        endpoint='/',
        agent_card: AgentCard = None,
        task_manager: TaskManager = None,
    ):
        self.host = host
        self.port = port
        self.endpoint = endpoint
        self.task_manager = task_manager
        self.agent_card = agent_card
        self.registered_agents: dict[str, AgentCard] = {}
        self.minion_message_queues: dict[str, list] = defaultdict(list) # In-memory message queues per minion
        self.app = Starlette()
        self.app.add_route(
            self.endpoint, self._process_request, methods=['POST']
        )
        self.app.add_route(
            '/.well-known/agent.json', self._get_agent_card, methods=['GET']
        )
        self.app.add_route(
            '/status', self._get_status, methods=['GET']
        )
        self.app.add_route(
            '/agents', self._handle_agents_request, methods=['GET', 'POST']
        )
        self.app.add_route(
            '/agents/{minion_id}/messages', self._handle_minion_messages, methods=['GET', 'POST'] # Allow GET and POST
        )

    def start(self):
        if self.agent_card is None:
            raise ValueError('agent_card is not defined')

        if self.task_manager is None:
            raise ValueError('request_handler is not defined')

        import uvicorn

        uvicorn.run(self.app, host=self.host, port=self.port)

    def _get_agent_card(self, request: Request) -> JSONResponse:
        return JSONResponse(self.agent_card.model_dump(exclude_none=True))

    async def _get_status(self, request: Request) -> JSONResponse:
        # Basic status endpoint
        logger.info("GET /status requested")
        return JSONResponse({'status': 'ok', 'agent_name': self.agent_card.name, 'version': self.agent_card.version})

    async def _handle_agents_request(self, request: Request) -> JSONResponse:
        if request.method == 'GET':
            logger.info(f"GET /agents requested - returning {len(self.registered_agents)} registered agents.")
            # Return list of agent card dicts
            agent_list = [agent.model_dump(exclude_none=True) for agent in self.registered_agents.values()]
            return JSONResponse(agent_list)
        elif request.method == 'POST':
            logger.info("POST /agents - Agent registration attempt received.")
            try:
                agent_card_json = await request.json()
                # Validate the received data using the AgentCard model
                try:
                    new_agent_card = AgentCard.model_validate(agent_card_json)
                except ValidationError as ve:
                    logger.error(f"Invalid agent card received for registration: {ve.errors()}", exc_info=True)
                    return JSONResponse({'status': 'error', 'message': 'Invalid agent card format', 'details': ve.errors()}, status_code=400)

                # Store the validated agent card
                # Use the 'name' from the validated AgentCard as the key for storage.
                # The AgentCard Pydantic model has a 'name' field.
                agent_id_to_store = new_agent_card.name
                if not agent_id_to_store:
                    logger.error("Validated agent card is missing 'name'. Cannot register.")
                    return JSONResponse({'status': 'error', 'message': "Validated agent card missing 'name'"}, status_code=400)
                
                self.registered_agents[agent_id_to_store] = new_agent_card
                logger.info(f"Agent '{new_agent_card.name}' (using name as ID: {agent_id_to_store}) registered successfully.")
                # The response 'id' here refers to the key used for storage, which is the agent's name.
                return JSONResponse({'status': 'registered', 'agent_name': new_agent_card.name, 'id': agent_id_to_store}, status_code=201)
            
            except json.JSONDecodeError:
                logger.error("Failed to decode JSON from agent registration request.", exc_info=True)
                return JSONResponse({'status': 'error', 'message': 'Invalid JSON format'}, status_code=400)
            except Exception as e:
                logger.error(f"Error processing agent registration: {e}", exc_info=True)
                return JSONResponse({'status': 'error', 'message': f'Failed to process registration: {str(e)}'}, status_code=500)

    async def _handle_minion_messages(self, request: Request) -> JSONResponse:
        minion_id = request.path_params['minion_id']
        
        if request.method == 'GET':
            messages_for_minion = self.minion_message_queues.get(minion_id, [])
            if messages_for_minion:
                logger.info(f"GET /agents/{minion_id}/messages - Delivering {len(messages_for_minion)} message(s).")
                # Return messages and clear the queue for this minion
                messages_to_send = list(messages_for_minion) # Create a copy
                self.minion_message_queues[minion_id] = [] # Clear the queue
                return JSONResponse(messages_to_send)
            else:
                logger.info(f"GET /agents/{minion_id}/messages - No messages found.")
                return JSONResponse([]) # Return empty list if no messages
        
        elif request.method == 'POST':
            logger.info(f"POST /agents/{minion_id}/messages - Message received for Minion {minion_id}.")
            try:
                message_payload = await request.json()
                # TODO: Validate message_payload if necessary (e.g., against a Message model)
                
                self.minion_message_queues[minion_id].append(message_payload)
                logger.info(f"Message for {minion_id} from {message_payload.get('sender_id', 'UnknownSender')} queued. Content: {str(message_payload.get('content', ''))[:100]}...")
                logger.debug(f"Current queue for {minion_id}: {self.minion_message_queues[minion_id]}")
                return JSONResponse({'status': 'message_queued', 'for_minion': minion_id}, status_code=202) # 202 Accepted
            except json.JSONDecodeError:
                logger.error(f"Failed to decode JSON from message for {minion_id}.", exc_info=True)
                return JSONResponse({'status': 'error', 'message': 'Invalid JSON format'}, status_code=400)
            except Exception as e:
                logger.error(f"Error processing message for {minion_id}: {e}", exc_info=True)
                return JSONResponse({'status': 'error', 'message': f'Failed to process message: {str(e)}'}, status_code=500)

    async def _process_request(self, request: Request):
        try:
            body = await request.json()
            json_rpc_request = A2ARequest.validate_python(body)

            if isinstance(json_rpc_request, GetTaskRequest):
                result = await self.task_manager.on_get_task(json_rpc_request)
            elif isinstance(json_rpc_request, SendTaskRequest):
                result = await self.task_manager.on_send_task(json_rpc_request)
            elif isinstance(json_rpc_request, SendTaskStreamingRequest):
                result = await self.task_manager.on_send_task_subscribe(
                    json_rpc_request
                )
            elif isinstance(json_rpc_request, CancelTaskRequest):
                result = await self.task_manager.on_cancel_task(
                    json_rpc_request
                )
            elif isinstance(json_rpc_request, SetTaskPushNotificationRequest):
                result = await self.task_manager.on_set_task_push_notification(
                    json_rpc_request
                )
            elif isinstance(json_rpc_request, GetTaskPushNotificationRequest):
                result = await self.task_manager.on_get_task_push_notification(
                    json_rpc_request
                )
            elif isinstance(json_rpc_request, TaskResubscriptionRequest):
                result = await self.task_manager.on_resubscribe_to_task(
                    json_rpc_request
                )
            else:
                logger.warning(
                    f'Unexpected request type: {type(json_rpc_request)}'
                )
                raise ValueError(f'Unexpected request type: {type(request)}')

            return self._create_response(result)

        except Exception as e:
            return self._handle_exception(e)

    def _handle_exception(self, e: Exception) -> JSONResponse:
        if isinstance(e, json.decoder.JSONDecodeError):
            json_rpc_error = JSONParseError()
        elif isinstance(e, ValidationError):
            json_rpc_error = InvalidRequestError(data=json.loads(e.json()))
        else:
            logger.error(f'Unhandled exception: {e}')
            json_rpc_error = InternalError()

        response = JSONRPCResponse(id=None, error=json_rpc_error)
        return JSONResponse(
            response.model_dump(exclude_none=True), status_code=400
        )

    def _create_response(
        self, result: Any
    ) -> JSONResponse | EventSourceResponse:
        if isinstance(result, AsyncIterable):

            async def event_generator(result) -> AsyncIterable[dict[str, str]]:
                async for item in result:
                    yield {'data': item.model_dump_json(exclude_none=True)}

            return EventSourceResponse(event_generator(result))
        if isinstance(result, JSONRPCResponse):
            return JSONResponse(result.model_dump(exclude_none=True))
        logger.error(f'Unexpected result type: {type(result)}')
        raise ValueError(f'Unexpected result type: {type(result)}')
