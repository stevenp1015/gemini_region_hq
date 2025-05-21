import React, { useState, useEffect } from 'react';
// import { getMinions } from '../../services/apiService'; // For later API integration
import './MinionList.css';

const MinionList = () => {
  const [minions, setMinions] = useState([
    { id: 'minion_alpha_001', name: 'ADKMinion-minion_alpha', status: 'Idle', task: 'None' },
    { id: 'minion_beta_002', name: 'ADKMinion-minion_beta', status: 'Working', task: 'Processing data for report X' },
    { id: 'minion_gamma_003', name: 'ADKMinion-minion_gamma', status: 'Error', task: 'File system access denied on /data/input.txt' },
  ]);
  const [selectedMinion, setSelectedMinion] = useState(null);

  // useEffect(() => {
  //   // Placeholder for fetching minions
  //   // getMinions().then(data => setMinions(data)).catch(err => console.error("Failed to fetch minions", err));
  //   console.log("MinionList: Fetching minions (mocked for now)");
  // }, []);

  const handleMinionClick = (minion) => {
    setSelectedMinion(minion);
    console.log("Selected Minion:", minion.name);
    // Here you might trigger display of MinionStatus or other actions
  };

  return (
    <div className="minion-list-container">
      <h4>Minion Roster</h4>
      {minions.length === 0 ? (
        <p>No minions available.</p>
      ) : (
        <ul>
          {minions.map((minion) => (
            <li 
              key={minion.id} 
              onClick={() => handleMinionClick(minion)}
              className={selectedMinion && selectedMinion.id === minion.id ? 'selected' : ''}
            >
              <span className={`status-dot status-${minion.status.toLowerCase()}`}></span>
              {minion.name} ({minion.status})
            </li>
          ))}
        </ul>
      )}
      {/* Basic MinionStatus display integrated or could be separate component */}
      {selectedMinion && (
        <div className="minion-details-simple">
          <h5>Details for {selectedMinion.name}</h5>
          <p><strong>ID:</strong> {selectedMinion.id}</p>
          <p><strong>Status:</strong> {selectedMinion.status}</p>
          <p><strong>Current Task:</strong> {selectedMinion.task}</p>
        </div>
      )}
    </div>
  );
};

export default MinionList;
