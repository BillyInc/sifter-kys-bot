import React, { createContext, useContext, useEffect, useState } from 'react';
import DatabaseService from './DatabaseService';

const DatabaseContext = createContext(null);

export const useDatabase = () => useContext(DatabaseContext);

export const DatabaseProvider = ({ children }) => {
  const [db, setDb] = useState(null);

  useEffect(() => {
    const init = async () => {
      const instance = await DatabaseService.init();
      setDb(instance);
    };
    init();
  }, []);

  return (
    <DatabaseContext.Provider value={DatabaseService}>
      {children}
    </DatabaseContext.Provider>
  );
};
