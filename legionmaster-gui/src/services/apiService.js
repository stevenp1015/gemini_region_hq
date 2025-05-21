// Simulates API calls to an ADK backend (LegionMaster or dedicated API Gateway Agent)
// In a real application, this would use fetch, axios, or WebSocket.

const MOCK_DELAY = 500; // Simulate network latency

// --- Minion API Stubs ---
export const getMinions = async () => {
  console.log('apiService: getMinions called');
  return new Promise(resolve => {
    setTimeout(() => {
      resolve([
        { id: 'minion_alpha_001', name: 'ADKMinion-minion_alpha', status: 'Idle', task: 'None', capabilities: ['File System Access', 'Data Analysis'] },
        { id: 'minion_beta_002', name: 'ADKMinion-minion_beta', status: 'Working', task: 'Generating report for Q3 sales', capabilities: ['Text Summarization', 'Web Search'] },
        { id: 'minion_gamma_003', name: 'ADKMinion-minion_gamma', status: 'Error', task: 'Image processing failed: unsupported format', capabilities: ['Image Processing', 'Code Execution'] },
        { id: 'decomposer_001', name: 'DecomposerMinion', status: 'Idle', task: 'None', capabilities: ['Task Decomposition'] },
        { id: 'summarizer_001', name: 'SummarizerMinion', status: 'Idle', task: 'None', capabilities: ['Text Summarization'] },
      ]);
    }, MOCK_DELAY);
  });
};

export const getMinionStatus = async (minionId) => {
  console.log(`apiService: getMinionStatus called for ${minionId}`);
  return new Promise((resolve, reject) => {
    setTimeout(() => {
      // Example: find minion from a mock list or return specific mock data
      const allMinions = [ /* copy from getMinions or maintain separate list */ ];
      const minion = allMinions.find(m => m.id === minionId);
      if (minion) {
        resolve(minion);
      } else {
        resolve({ id: minionId, name: `Unknown Minion ${minionId}`, status: 'Unknown', task: 'N/A', capabilities: [] });
      }
    }, MOCK_DELAY);
  });
};

// --- Chat API Stubs ---
export const getChatChannels = async () => {
  console.log('apiService: getChatChannels called');
  return new Promise(resolve => {
    setTimeout(() => {
      resolve([
        { id: 'chat_dev_general', name: 'General Development Chat', unread: 2, description: 'Main chat for dev team.' },
        { id: 'chat_minion_alpha_tasks', name: 'Minion Alpha Tasks', unread: 0, description: 'Tasks and logs for Minion Alpha.' },
        { id: 'dm_userx_legionmaster', name: 'DM: UserX - LegionMaster', unread: 1, description: 'Direct message with LegionMaster.' },
        { id: 'chat_alerts', name: 'System Alerts', unread: 5, description: 'Critical system alerts and notifications.' },
      ]);
    }, MOCK_DELAY);
  });
};

export const getChatHistory = async (channelId) => {
  console.log(`apiService: getChatHistory called for ${channelId}`);
  // currentUserId is needed to determine 'isOwnMessage' if not stored directly with message
  const currentUserId = "CurrentUser_001"; // Example, should come from auth context
  return new Promise(resolve => {
    setTimeout(() => {
      const histories = {
        'chat_dev_general': [
          { id: 'msg1', senderName: 'ADKMinion-minion_alpha', text: 'Hello team! Started work on photosynthesis decomposition.', timestamp: Date.now() - 200000 },
          { id: 'msg2', senderName: 'UserX', text: 'Great! Keep us posted.', timestamp: Date.now() - 100000 },
          { id: 'msg3', senderName: currentUserId, text: 'I will be monitoring the progress.', timestamp: Date.now() - 50000 },
          { id: 'msg4', senderName: 'ADKMinion-minion_beta', text: 'I can help with the summarization part if needed.', timestamp: Date.now() - 20000 },
        ],
        'chat_minion_alpha_tasks': [
            {id: 'taskmsg1', senderName: 'LegionMaster', text: 'Minion Alpha, please research topic X.', timestamp: Date.now() - 60000}
        ],
        'dm_userx_legionmaster': [
            {id: 'dm1', senderName: 'UserX', text: 'LegionMaster, what is the overall status?', timestamp: Date.now() - 120000}
        ],
        'chat_alerts': [
            {id: 'alert1', senderName: 'System', text: 'High CPU usage detected on Minion Gamma.', timestamp: Date.now() - 10000}
        ]
      };
      // Add isOwnMessage property based on sender.
      const channelHistory = (histories[channelId] || []).map(msg => ({...msg, isOwnMessage: msg.senderName === currentUserId }));
      resolve(channelHistory);
    }, MOCK_DELAY);
  });
};

export const sendMessage = async (channelId, messageText) => {
  console.log(`apiService: sendMessage to ${channelId}: ${messageText}`);
  const currentUserId = "CurrentUser_001"; // Example
  return new Promise(resolve => {
    setTimeout(() => {
      const sentMessage = {
        id: `msg${Date.now()}`, // Server should generate ID
        senderName: currentUserId, 
        text: messageText,
        timestamp: Date.now(),
        isOwnMessage: true, // From perspective of sender
        channelId: channelId 
      };
      console.log("apiService: Mock message sent:", sentMessage);
      // In a real scenario, the server would broadcast this, and client would receive it via WebSocket.
      // For stub, we just resolve it, and ChatWindow component adds it to its local state (optimistic update).
      resolve(sentMessage); 
    }, MOCK_DELAY);
  });
};

// --- Task/Directive API Stubs ---
export const sendTaskToLegionMaster = async (taskDescription) => {
  console.log(`apiService: sendTaskToLegionMaster: ${taskDescription}`);
  return new Promise(resolve => {
    setTimeout(() => {
      console.log(`Task "${taskDescription}" notionally sent to LegionMaster.`);
      resolve({ status: 'TaskReceived', taskId: `task_${Date.now()}`, message: 'LegionMaster has received the task.' });
    }, MOCK_DELAY);
  });
};

export const sendDirectiveToMinion = async (minionId, directive) => {
  console.log(`apiService: sendDirectiveToMinion ${minionId}: ${directive}`);
  return new Promise(resolve => {
    setTimeout(() => {
      console.log(`Directive "${directive}" notionally sent to Minion ${minionId}.`);
      resolve({ status: 'DirectiveReceived', minionId: minionId, message: `Minion ${minionId} has received the directive.` });
    }, MOCK_DELAY);
  });
};

// --- WebSocket Simulation Outline (Conceptual) ---
// let mockWebSocket = null;
// export const connectToActivityStream = (onNewActivity) => {
//   console.log('apiService: Attempting to connect to WebSocket for activity stream...');
//   // Simulate WebSocket connection
//   mockWebSocket = {
//     send: (message) => console.log('MockWebSocket sent:', message),
//     close: () => console.log('MockWebSocket closed.'),
//   };
//   // Simulate receiving messages
//   setInterval(() => {
//     if (onNewActivity) {
//       const mockActivity = { 
//         id: `act_${Date.now()}`, 
//         timestamp: Date.now(), 
//         text: `Mock real-time activity: Minion Zeta completed sub-task ${Math.floor(Math.random() * 100)}.`
//       };
//       onNewActivity(mockActivity);
//     }
//   }, 5000); // New activity every 5 seconds
//   console.log('apiService: Mock WebSocket connected.');
//   return mockWebSocket;
// };

// export const disconnectFromActivityStream = () => {
//   if (mockWebSocket) {
//     mockWebSocket.close();
//     mockWebSocket = null;
//   }
// };

console.log('apiService.js loaded. Contains stub functions for ADK backend interaction.');
