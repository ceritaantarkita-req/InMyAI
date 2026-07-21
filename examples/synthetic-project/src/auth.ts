export type User = { id: string; email: string; role: 'admin' | 'member' };

export function canOpenAdmin(user: User): boolean {
  return user.role === 'admin';
}
