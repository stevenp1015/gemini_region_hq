import React, { useState } from 'react';
import './MainDashboard.css';

// Import actual components
import MinionList from '../MinionDisplay/MinionList';
import ChannelList from '../Chat/ChannelList';
import ChatWindow from '../Chat/ChatWindow';
import TaskInput from '../TaskControl/TaskInput';
import ActivityMonitor from './ActivityMonitor'; // Already in Dashboard folder

const MainDashboard = () => {
  const [currentChannelId, setCurrentChannelId] = useState(null);
  const [currentChannelName, setCurrentChannelName] = useState('');
  // const [selectedMinionId, setSelectedMinionId] = useState(null); // MinionList handles its own selection for now

  const handleChannelSelect = (channelId, channelName) => {
    // In a real app, channelName might come from the channel object itself
    // For simplicity, if ChannelList only passes ID, we might need to find name or have ChannelList pass more info
    setCurrentChannelId(channelId);
    const name = channelId.startsWith('dm_') ? `DM (${channelId.split('_')[1]})` : channelId.replace('chat_', '').replace('_', ' ');
    setCurrentChannelName(channelName || name); 
    console.log(`MainDashboard: Selected channel ID: ${channelId}, Name: ${channelName || name}`);
  };
  
  // This function would be passed to MinionList if MainDashboard needs to know about selected minion
  // const handleMinionSelect = (minionId) => {
  //   setSelectedMinionId(minionId);
  //   console.log(`MainDashboard: Selected Minion ID: ${minionId}`);
  // };

  return (
    <div className="main-dashboard">
      <div className="dashboard-header">
        <h2>Dashboard Overview</h2>
      </div>
      <div className="dashboard-layout">
        <div className="left-panel">
          {/* <MinionList onSelectMinion={handleMinionSelect} /> */}
          <MinionList /> {/* MinionList currently handles its own detail display */}
          <ChannelList onSelectChannel={(id) => handleChannelSelect(id, /* placeholder for name if not passed by ChannelList */ null)} />
        </div>
        <div className="center-panel">
          <ChatWindow currentChannelId={currentChannelId} currentChannelName={currentChannelName} />
        </div>
        <div className="right-panel">
          <TaskInput />
          <ActivityMonitor /> 
          {/* MinionStatus placeholder was integrated into MinionList for now */}
          {/* If a dedicated MinionStatus component were used: */}
          {/* {selectedMinionId && <MinionStatus minionId={selectedMinionId} />} */}
        </div>
      </div>
    </div>
  );
};

export default MainDashboard;
