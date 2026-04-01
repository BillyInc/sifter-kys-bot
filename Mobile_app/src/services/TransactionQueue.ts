import AsyncStorage from '@react-native-async-storage/async-storage';
import NetInfo from '@react-native-community/netinfo';
import PushNotification from 'react-native-push-notification';

interface QueuedTransaction {
  id: number;
  attempts: number;
  createdAt: number;
  token?: string;
  [key: string]: any;
}

class TransactionQueue {
  private queue: QueuedTransaction[];
  private processing: boolean;
  private maxRetries: number;

  constructor() {
    this.queue = [];
    this.processing = false;
    this.maxRetries = 5;
  }

  async addTransaction(tx: any): Promise<void> {
    this.queue.push({ ...tx, id: Date.now() + Math.random(), attempts: 0, createdAt: Date.now() });
    await this.saveQueue();
    if (!this.processing) this.processQueue();
  }

  async processQueue(): Promise<void> {
    this.processing = true;
    while (this.queue.length > 0) {
      const tx = this.queue[0];
      const network = await NetInfo.fetch();
      if (!network.isConnected) {
        await this.delay(30000);
        continue;
      }
      try {
        await this.executeTransaction(tx);
        this.queue.shift();
        await this.saveQueue();
      } catch (e: any) {
        tx.attempts++;
        if (tx.attempts >= this.maxRetries) {
          await this.moveToDeadLetter(tx);
          this.queue.shift();
          PushNotification.localNotification({
            channelId: 'trades',
            title: '❌ Transaction Failed',
            message: `${tx.token}: Failed after ${this.maxRetries} attempts`,
            importance: 'high'
          } as any);
        } else {
          this.queue.shift();
          this.queue.push(tx);
          await this.delay(10000 * tx.attempts);
        }
      }
    }
    this.processing = false;
  }

  async executeTransaction(tx: QueuedTransaction): Promise<void> {
    // Delegate back to FortifiedAutoTrader — imported lazily to avoid circular dep
    const { default: trader } = await import('./FortifiedAutoTrader');
    await trader.executeFromQueue(tx);
  }

  async saveQueue(): Promise<void> {
    await AsyncStorage.setItem('transaction_queue', JSON.stringify(this.queue));
  }

  async loadQueue(): Promise<void> {
    const saved = await AsyncStorage.getItem('transaction_queue');
    if (saved) {
      this.queue = JSON.parse(saved);
      if (this.queue.length > 0) this.processQueue();
    }
  }

  async moveToDeadLetter(tx: QueuedTransaction): Promise<void> {
    const deadLetter = JSON.parse(await AsyncStorage.getItem('dead_letter_queue') || '[]');
    deadLetter.push({ ...tx, failedAt: Date.now() });
    await AsyncStorage.setItem('dead_letter_queue', JSON.stringify(deadLetter));
  }

  delay(ms: number): Promise<void> { return new Promise(r => setTimeout(r, ms)); }
}

export const transactionQueue = new TransactionQueue();
export default transactionQueue;
