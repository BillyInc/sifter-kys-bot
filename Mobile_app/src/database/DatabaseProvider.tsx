import React, { createContext, useContext, useEffect, useState } from 'react';
import DatabaseService from './DatabaseService';

const DatabaseContext = createContext<typeof DatabaseService | null>(null);

export const useDatabase = () => useContext(DatabaseContext);

interface DatabaseProviderProps {
  children: React.ReactNode;
}

export const DatabaseProvider: React.FC<DatabaseProviderProps> = ({ children }) => {
  const [db, setDb] = useState<any>(null);

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
