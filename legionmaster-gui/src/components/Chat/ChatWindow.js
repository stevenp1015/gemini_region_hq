import React, { useState, useEffect, useRef } from 'react';
// import { getChatHistory, sendMessage as apiSendMessage } from '../../services/apiService'; // For later
import ChatMessage from './ChatMessage';
import ChatInput from './ChatInput';
import './ChatWindow.css';

const ChatWindow = ({ currentChannelId, currentChannelName, currentUserId = "CurrentUser_001" }) => {
  const [messages, setMessages] = useState([]);
  const messagesEndRef = useRef(null); // For auto-scrolling

  // Mock messages for now
  const initialMessages = {
    'chat_dev_general': [
      { id: 'msg1', senderName: 'ADKMinion-minion_alpha', text: 'Hello team! Started work on photosynthesis decomposition.', timestamp: Date.now() - 200000, isOwnMessage: false },
      { id: 'msg2', senderName: 'UserX', text: 'Great! Keep us posted.', timestamp: Date.now() - 100000, isOwnMessage: false },
      { id: 'msg3', senderName: currentUserId, text: 'I will be monitoring the progress.', timestamp: Date.now() - 50000, isOwnMessage: true },
      { id: 'msg4', senderName: 'ADKMinion-minion_beta', text: 'I can help with the summarization part if needed.', timestamp: Date.now() - 20000, isOwnMessage: false },
    ],
    'chat_minion_alpha_tasks': [
        {id: 'taskmsg1', senderName: 'LegionMaster', text: 'Minion Alpha, please research topic X.', timestamp: Date.now() - 60000, isOwnMessage: false}
    ]
  };

  useEffect(() => {
    if (currentChannelId) {
      console.log(`ChatWindow: Fetching history for channel ${currentChannelId} (mocked)`);
      // getChatHistory(currentChannelId).then(data => setMessages(data)).catch(err => console.error("Failed to fetch chat history", err));
      setMessages(initialMessages[currentChannelId] || []);
    } else {
      setMessages([]); // Clear messages if no channel selected
    }
  }, [currentChannelId]); // Reload messages when channel changes

  useEffect(() => {
    // Auto-scroll to the bottom whenever messages change
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSendMessage = (channelId, text) => {
    console.log(`Sending message to ${channelId}: ${text}`);
    const newMessage = {
      id: `msg${Date.now()}`, // Temporary ID
      senderName: currentUserId, // Assume current user is sending
      text: text,
      timestamp: Date.now(),
      isOwnMessage: true,
    };
    // apiSendMessage(channelId, text)
    //   .then(sentMessage => setMessages(prevMessages => [...prevMessages, sentMessage]))
    //   .catch(err => console.error("Failed to send message", err));
    
    // Local echo for now
    setMessages(prevMessages => [...prevMessages, newMessage]);
  };

  if (!currentChannelId) {
    return <div className="chat-window-placeholder-select">Please select a channel to start chatting.</div>;
  }

  return (
    <div className="chat-window-container">
      <div className="chat-window-header">
        <h3>{currentChannelName || 'Chat'}</h3>
      </div>
      <div className="message-list">
        {messages.length === 0 ? (
          <p className="no-messages-notice">No messages in this channel yet. Start the conversation!</p>
        ) : (
          messages.map(msg => <ChatMessage key={msg.id} message={msg} />)
        )}
        <div ref={messagesEndRef} /> {/* Element to scroll to */}
      </div>
      <ChatInput onSendMessage={handleSendMessage} currentChannelId={currentChannelId} />
    </div>
  );
};

export default ChatWindow;
