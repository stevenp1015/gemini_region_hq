import React, { useState, useEffect } from 'react';
import './ActivityMonitor.css';

const ActivityMonitor = () => {
  const [activities, setActivities] = useState([
    { id: 'act1', timestamp: Date.now() - 300000, text: 'LegionMaster: Delegated task "Analyze Photosynthesis" to DecomposerMinion.' },
    { id: 'act2', timestamp: Date.now() - 250000, text: 'DecomposerMinion: Task "Analyze Photosynthesis" decomposed into 3 steps.' },
    { id: 'act3', timestamp: Date.now() - 200000, text: 'WorkerMinion_1: Executing "Describe light-dependent reactions"...' },
    { id: 'act4', timestamp: Date.now() - 150000, text: 'ChatCoordinator (chat_dev_general): ADKMinion-minion_alpha says "Hello team!"' },
    { id: 'act5', timestamp: Date.now() - 100000, text: 'WorkerMinion_1: Completed "Describe light-dependent reactions".' },
    { id: 'act6', timestamp: Date.now() - 50000, text: 'SummarizerMinion: Received 3 reports for "Analyze Photosynthesis". Generating summary.' },
  ]);

  // useEffect(() => {
  //   // Placeholder for fetching initial logs or connecting to a WebSocket for real-time logs
  //   // e.g., connectToActivityStream((newActivity) => {
  //   //   setActivities(prevActivities => [newActivity, ...prevActivities]);
  //   // });
  //   console.log("ActivityMonitor: Initialized (mock data for now)");
  // }, []);

  return (
    <div className="activity-monitor-container">
      <h4>System Activity Log</h4>
      <div className="activity-list">
        {activities.length === 0 ? (
          <p>No recent activity.</p>
        ) : (
          activities.map(activity => (
            <div key={activity.id} className="activity-item">
              <span className="activity-timestamp">
                {new Date(activity.timestamp).toLocaleTimeString()}
              </span>
              <span className="activity-text">{activity.text}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default ActivityMonitor;
