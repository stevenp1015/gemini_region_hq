// src/main.js
// Modified to run as a persistent service.

import express from 'express';
import { mcpClientManager } from './mcp_client_manager.js';
// import { GeminiInteractor } from './gemini_interactor.js'; // No longer needed for direct chat
// import { buildSystemPrompt } from './prompt_builder.js'; // System prompt construction might be needed elsewhere or differently
// import { parseToolCall } from './tool_parser.js'; // Tool parsing is now handled by the caller of /execute

const app = express();
const port = process.env.MCP_SERVICE_PORT || 3000;

app.use(express.json()); // Middleware to parse JSON bodies

async function startService() {
    console.log("==============================================");
    console.log("  Node.js MCP Service (Codex Omega)         ");
    console.log("==============================================");

    console.log("\nInitializing MCP Client Manager...");
    try {
        await mcpClientManager.initialize();
    } catch (initError) {
        console.error("CRITICAL: Failed to initialize MCP Client Manager. Exiting.", initError);
        process.exit(1);
    }

    const connectedServersAndTools = mcpClientManager.getConnectedServersAndTools();
    if (connectedServersAndTools.length === 0) {
        console.warn("\nWARNING: No MCP servers are connected or they reported no tools.");
    } else {
        console.log("\nConnected MCP Servers and discovered tools:");
        connectedServersAndTools.forEach(s => {
            console.log(`- Server: ${s.name} (${s.tools.length} tools)`);
        });
    }

    // Endpoint to get available MCP tools
    app.get('/tools', (req, res) => {
        try {
            const tools = mcpClientManager.getConnectedServersAndTools();
            res.json(tools);
        } catch (error) {
            console.error("[Service /tools] Error fetching tools:", error);
            res.status(500).json({ error: "Failed to retrieve MCP tools", details: error.message });
        }
    });

    // Endpoint to execute an MCP tool
    app.post('/execute', async (req, res) => {
        const { server_name, tool_name, arguments: tool_arguments } = req.body;

        if (!server_name || !tool_name) {
            return res.status(400).json({ error: "Missing 'server_name' or 'tool_name' in request body" });
        }

        console.log(`\n[Service /execute] Request to execute tool: ${tool_name} on server: ${server_name}`);
        console.log(`  Arguments: ${JSON.stringify(tool_arguments)}`);

        try {
            const result = await mcpClientManager.callTool(server_name, tool_name, tool_arguments);
            console.log(`[Service /execute] Tool ${tool_name} execution result:`, result.isError ? `Error: ${JSON.stringify(result.content)}` : "Success");
            res.json(result);
        } catch (error) {
            console.error(`[Service /execute] Error executing tool ${tool_name} on ${server_name}:`, error);
            res.status(500).json({ error: `Failed to execute MCP tool ${tool_name}`, details: error.message });
        }
    });

    // Basic error handling middleware (optional, can be expanded)
    app.use((err, req, res, next) => {
        console.error("[Service Error] Unhandled error:", err.stack);
        res.status(500).send('Something broke!');
    });


    app.listen(port, () => {
        console.log(`\nNode.js MCP Service listening on port ${port}`);
        console.log("Endpoints available:");
        console.log(`  GET  /tools          - Lists available MCP tools`);
        console.log(`  POST /execute        - Executes an MCP tool`);
        console.log("---------------------------------------------------------------------------\n");
    });
}

// Graceful shutdown
async function shutdown() {
    console.log("\nShutting down MCP Service...");
    await mcpClientManager.shutdown();
    console.log("MCP Client Manager shut down.");
    // Add any other cleanup here
    process.exit(0);
}

process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);


// Unhandled rejection/exception catcher for robustness.
process.on('unhandledRejection', (reason, promise) => {
  console.error('[Unhandled Rejection at Promise]:', promise, 'Reason:', reason);
  // Consider a more graceful shutdown or logging to a persistent store
  process.exit(1);
});
process.on('uncaughtException', (error) => {
  console.error('[Uncaught Exception]:', error);
  process.exit(1);
});


startService().catch(error => {
    console.error("[Service Main] FATAL ERROR during service startup:", error);
    mcpClientManager.shutdown().finally(() => process.exit(1));
});