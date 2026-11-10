const { parsePayment, isDuplicate } = require('./paymentParser');
const fixtures = require('./fixtures.json');
let pass = 0, fail = 0;
for (const f of fixtures) {
  const got = parsePayment(f.text, { receivedAt: '2026-11-08T10:15:00Z' });
  let ok = true;
  if (f.expect === null) ok = got === null;
  else if (!got) ok = false;
  else for (const [k, v] of Object.entries(f.expect)) if (got[k] !== v) ok = false;
  if (ok) pass++; else { fail++; console.log('FAIL:', f.name, '\n  got:', JSON.stringify(got), '\n  want:', JSON.stringify(f.expect)); }
}
// dedupe: bank SMS + GPay notification for the same ₹250 payment 20s apart
const a = parsePayment(fixtures[0].text, { receivedAt: '2026-11-08T10:15:00Z' });
const b = parsePayment(fixtures[6].text, { receivedAt: '2026-11-08T10:15:20Z', source: 'notification' });
if (isDuplicate(a, b)) pass++; else { fail++; console.log('FAIL: dedupe sms+notification'); }
console.log(`${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
