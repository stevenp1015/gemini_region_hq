import React, { useState, useEffect } from 'react';
// import { getChatChannels } from '../../services/apiService'; // For later
import './ChannelList.css';

const ChannelList = ({ onSelectChannel }) => {
  const [channels, setChannels] = useState([
    { id: 'chat_dev_general', name: 'General Development Chat', unread: 2 },
    { id: 'chat_minion_alpha_tasks', name: 'Minion Alpha Tasks', unread: 0 },
    { id: 'dm_userx_legionmaster', name: 'DM: UserX - LegionMaster', unread: 1 },
  ]);
  const [selectedChannelId, setSelectedChannelId] = useState(null);

  // useEffect(() => {
  //   getChatChannels().then(data => setChannels(data)).catch(err => console.error("Failed to fetch channels", err));
  // }, []);

  const handleChannelSelect = (channel) => {
    setSelectedChannelId(channel.id);
    if (onSelectChannel) {
      onSelectChannel(channel.id); // Notify parent component
    }
    console.log("Selected Channel:", channel.name);
  };

  return (
    <div className="channel-list-container">
      <h4>Chat Channels</h4>
      {channels.length === 0 ? (
        <p>No channels available.</p>
      ) : (
        <ul>
          {channels.map((channel) => (
            <li 
              key={channel.id} 
              onClick={() => handleChannelSelect(channel)}
              className={selectedChannelId === channel.id ? 'selected' : ''}
            >
              {channel.name} 
              {channel.unread > 0 && <span className="unread-count">{channel.unread}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default ChannelList;
