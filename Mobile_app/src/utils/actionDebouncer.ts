// Global debouncer — prevents double-execution of any action app-wide.
// Usage:
//   await actionDebouncer.execute('buy_0xTokenAddr', async () => { ... }, { cooldownMs: 5000 })

interface ExecuteOptions {
  cooldownMs?: number;
  preventDouble?: boolean;
  timeoutMs?: number;
}

class ActionDebouncer {
  private actions: Map<string, number>;
  private pending: Map<string, boolean>;

  constructor() {
    this.actions = new Map();    // actionId -> last execution timestamp
    this.pending = new Map();    // actionId -> boolean
  }

  async execute(actionId: string, actionFn: () => Promise<any>, options: ExecuteOptions = {}): Promise<any> {
    const { cooldownMs = 2000, preventDouble = true, timeoutMs = 30000 } = options;
    const now = Date.now();
    const lastRun = this.actions.get(actionId) || 0;
    const isProcessing = this.pending.get(actionId) || false;

    if (now - lastRun < cooldownMs) {
      throw new Error(`Please wait ${Math.ceil((cooldownMs - (now - lastRun)) / 1000)}s before trying again`);
    }

    if (preventDouble && isProcessing) {
      throw new Error('Already processing — please wait');
    }

    this.pending.set(actionId, true);

    try {
      const result = await Promise.race([
        actionFn(),
        new Promise((_, reject) => setTimeout(() => reject(new Error('Action timed out')), timeoutMs))
      ]);
      this.actions.set(actionId, Date.now());
      return result;
    } finally {
      this.pending.set(actionId, false);
    }
  }

  isProcessing(actionId: string): boolean {
    return this.pending.get(actionId) || false;
  }

  reset(actionId: string): void {
    this.actions.delete(actionId);
    this.pending.delete(actionId);
  }
}

export const actionDebouncer = new ActionDebouncer();
export default actionDebouncer;
