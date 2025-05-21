import React from 'react';
import './App.css';
import MainDashboard from './components/Dashboard/MainDashboard'; // We will create this next

function App() {
  return (
    <div className="App">
      <header className="App-header">
        <h1>LegionMaster GUI</h1>
      </header>
      <MainDashboard />
    </div>
  );
}

export default App;
