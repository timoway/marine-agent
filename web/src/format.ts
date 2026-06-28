export const FLORIDA_TZ = 'America/New_York';

export function formatFloridaTime(isoTimestamp: string): string {
  return new Date(isoTimestamp).toLocaleString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    timeZone: FLORIDA_TZ,
    timeZoneName: 'short',
  });
}