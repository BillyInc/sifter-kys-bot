// api/client.ts
const API_BASE: string = import.meta.env.VITE_API_URL || 'http://localhost:5000';

interface RequestOptions extends RequestInit {
  headers?: Record<string, string>;
}

async function apiRequest<T = any>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  const defaultOptions: RequestOptions = {
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
  getSalt: (userId: string): Promise<any> => apiRequest(`/api/diary/salt?user_id=${userId}`),
  saveSalt: (data: Record<string, unknown>): Promise<any> => apiRequest('/api/diary/salt', { method: 'POST', body: JSON.stringify(data) }),
  getNotes: (userId: string, walletAddress?: string): Promise<any> => {
    let url = `/api/diary/notes?user_id=${userId}`;
    if (walletAddress) url += `&wallet_address=${walletAddress}`;
    return apiRequest(url);
  },
  createNote: (data: Record<string, unknown>): Promise<any> => apiRequest('/api/diary/notes', { method: 'POST', body: JSON.stringify(data) }),
  updateNote: (noteId: string, data: Record<string, unknown>): Promise<any> => apiRequest(`/api/diary/notes/${noteId}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteNote: (noteId: string, userId: string): Promise<any> => apiRequest(`/api/diary/notes/${noteId}`, {
    method: 'DELETE',
    body: JSON.stringify({ user_id: userId })
  }),
};
