import React, { useState } from 'react';
import './ChatInput.css';

const ChatInput = ({ onSendMessage, currentChannelId }) => {
  const [messageText, setMessageText] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (messageText.trim() === '') {
      return; // Don't send empty messages
    }
    if (!currentChannelId) {
        alert("Please select a channel first.");
        return;
    }
    
    onSendMessage(currentChannelId, messageText); // Pass channelId and text
    setMessageText(''); // Clear input after sending
  };

  return (
    <form onSubmit={handleSubmit} className="chat-input-form">
      <input
        type="text"
        value={messageText}
        onChange={(e) => setMessageText(e.target.value)}
        placeholder="Type your message..."
        className="chat-input-field"
        disabled={!currentChannelId} // Disable if no channel selected
      />
      <button type="submit" className="chat-send-button" disabled={!currentChannelId || messageText.trim() === ''}>
        Send
      </button>
    </form>
  );
};

export default ChatInput;
