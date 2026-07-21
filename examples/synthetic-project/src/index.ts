import { canOpenAdmin, type User } from './auth';

const demoUser: User = { id: 'u_1', email: 'demo@example.com', role: 'admin' };
console.log(canOpenAdmin(demoUser));
