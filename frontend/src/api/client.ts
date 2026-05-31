import axios from 'axios';

// Use relative URLs so requests route through whatever reverse proxy serves the app
// (Nginx in production, Vite dev server proxy in development).
// VITE_API_URL can override for custom deployments.
const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? '',
});

export default apiClient;
