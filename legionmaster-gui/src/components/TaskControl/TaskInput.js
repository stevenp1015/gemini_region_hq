import React, { useState } from 'react';
// import { sendTaskToLegionMaster, sendDirectiveToMinion } from '../../services/apiService'; // For later
import './TaskInput.css';

const TaskInput = () => {
  const [taskText, setTaskText] = useState('');
  const [targetType, setTargetType] = useState('LegionMaster'); // 'LegionMaster' or 'Minion'
  const [minionId, setMinionId] = useState(''); // Only if targetType is 'Minion'

  const handleSubmit = (e) => {
    e.preventDefault();
    if (taskText.trim() === '') {
      alert('Please enter a task or directive.');
      return;
    }

    if (targetType === 'LegionMaster') {
      console.log(`Sending task to LegionMaster: ${taskText}`);
      // sendTaskToLegionMaster(taskText)
      //   .then(() => alert('Task sent to LegionMaster!'))
      //   .catch(err => alert(`Error sending task: ${err.message}`));
    } else if (targetType === 'Minion') {
      if (minionId.trim() === '') {
        alert('Please enter a Minion ID.');
        return;
      }
      console.log(`Sending directive to Minion ${minionId}: ${taskText}`);
      // sendDirectiveToMinion(minionId, taskText)
      //   .then(() => alert(`Directive sent to Minion ${minionId}!`))
      //   .catch(err => alert(`Error sending directive: ${err.message}`));
    }
    setTaskText(''); // Clear input
    // setMinionId(''); // Optionally clear minionId too
  };

  return (
    <div className="task-input-container">
      <h4>Send Task / Directive</h4>
      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="targetType">Target:</label>
          <select 
            id="targetType" 
            value={targetType} 
            onChange={(e) => setTargetType(e.target.value)}
          >
            <option value="LegionMaster">LegionMaster</option>
            <option value="Minion">Specific Minion</option>
          </select>
        </div>

        {targetType === 'Minion' && (
          <div className="form-group">
            <label htmlFor="minionId">Minion ID:</label>
            <input
              type="text"
              id="minionId"
              value={minionId}
              onChange={(e) => setMinionId(e.target.value)}
              placeholder="Enter Minion ID (e.g., minion_alpha)"
            />
          </div>
        )}

        <div className="form-group">
          <label htmlFor="taskText">Task / Directive:</label>
          <textarea
            id="taskText"
            value={taskText}
            onChange={(e) => setTaskText(e.target.value)}
            placeholder="Describe the task or directive..."
            rows="3"
          />
        </div>
        <button type="submit" className="send-task-button">Send Command</button>
      </form>
    </div>
  );
};

export default TaskInput;
