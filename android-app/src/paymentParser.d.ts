export interface ParsedPayment {
  direction: 'debit' | 'credit'; amount: number; currency: 'INR'; counterparty: string | null; counterpartyIsPerson: boolean | null;
  upiRef: string | null; accountLast4: string | null; instrument: 'upi' | 'card' | 'bank' | 'atm'; source: string; occurredAt: string; dedupeKey: string;
}
export function parsePayment(text: string, opts?: { source?: string; receivedAt?: string }): ParsedPayment | null;
export function isDuplicate(a: ParsedPayment, b: ParsedPayment, windowMs?: number): boolean;
export function looksLikePerson(name: string): boolean;
