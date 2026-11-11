export const PURCHASING_DEMO_ORG = "purchasing-demo";
export const PURCHASING_DEMO_DOMAIN = "purchasing-demo.aura.invalid";

export const purchasingDemoAccounts = [
  { label: "Purchasing", role: "purchasing", handle: "purchasing" },
  { label: "Vendor", role: "vendor", handle: "vendor" },
  { label: "L1", role: "approver", handle: "l1" },
  { label: "Finance", role: "finance", handle: "finance" },
].map((account) => ({
  ...account,
  id: `${PURCHASING_DEMO_ORG}-${account.handle}`,
  email: `${account.handle}@${PURCHASING_DEMO_DOMAIN}`,
  // These credentials are deliberately public and only grant access to synthetic demo data.
  password: `AURA public demo ${account.handle}`,
  workspaceId: PURCHASING_DEMO_ORG,
}));

export function isPurchasingDemoUser(userId: string) {
  return purchasingDemoAccounts.some((account) => account.id === userId);
}
