import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import axios from 'axios';

// Mock apiClient instance
const apiClient = {
  get: (url: string) => fetch(url).then(res => res.json()),
  post: (url: string, data: any) => fetch(url, { method: 'POST', body: JSON.stringify(data) }).then(res => res.json()),
};

export const Dashboard: React.FC<{ orgId: string }> = ({ orgId }) => {
  const [payload] = useState({ username: 'admin', password: 'secretpassword' });

  // React Query hook fetching analytics using apiClient
  const { data: analytics, isLoading } = useQuery({
    queryKey: ['analytics', orgId],
    queryFn: () => apiClient.get(`/api/v2/analytics/${orgId}`),
  });

  const handleLogin = async () => {
    // Axios post call for authentication
    const response = await axios.post('/api/v2/auth/login', payload);
    return response.data;
  };

  if (isLoading) return <div>Loading analytics...</div>;

  return (
    <div>
      <h1>Dashboard for Org: {orgId}</h1>
      <pre>{JSON.stringify(analytics, null, 2)}</pre>
      <button onClick={handleLogin}>Authenticate</button>
    </div>
  );
};

export default Dashboard;
