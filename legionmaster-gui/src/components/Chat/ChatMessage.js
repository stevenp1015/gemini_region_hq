import React from 'react';
import './ChatMessage.css';

const ChatMessage = ({ message }) => {
  // message object expected to have: id, senderName, text, timestamp, isOwnMessage (boolean)
  const { senderName, text, timestamp, isOwnMessage } = message;
  const messageClass = isOwnMessage ? 'chat-message own-message' : 'chat-message other-message';

  return (
    <div className={messageClass} title={timestamp ? new Date(timestamp).toLocaleString() : ''}>
      {!isOwnMessage && <div className="sender-name">{senderName || 'Unknown Sender'}</div>}
      <div className="message-text">{text}</div>
      {/* Optional: timestamp display can be added here if needed directly in message body */}
    </div>
  );
};

export default ChatMessage;
