// api/client.js
const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:5000';

async function apiRequest(endpoint, options = {}) {
  const defaultOptions = {
    headers: {
      'Accept': 'application/json',
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    mode: 'cors',
  };

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...defaultOptions,
    ...options,
    headers: {
      ...defaultOptions.headers,
      ...options.headers,
    },
  });

  if (!response.ok) {
    throw new Error(`API request failed: ${response.statusText}`);
  }

  return response.json();
}

export const diaryApi = {
  getSalt: (userId) => apiRequest(`/api/diary/salt?user_id=${userId}`),
  saveSalt: (data) => apiRequest('/api/diary/salt', { method: 'POST', body: JSON.stringify(data) }),
  getNotes: (userId, walletAddress) => {
    let url = `/api/diary/notes?user_id=${userId}`;
    if (walletAddress) url += `&wallet_address=${walletAddress}`;
    return apiRequest(url);
  },
  createNote: (data) => apiRequest('/api/diary/notes', { method: 'POST', body: JSON.stringify(data) }),
  updateNote: (noteId, data) => apiRequest(`/api/diary/notes/${noteId}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteNote: (noteId, userId) => apiRequest(`/api/diary/notes/${noteId}`, { 
    method: 'DELETE', 
    body: JSON.stringify({ user_id: userId }) 
  }),
};