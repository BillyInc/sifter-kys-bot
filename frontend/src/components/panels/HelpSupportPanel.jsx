import React, { useState } from 'react';
import { Search, Book, Video, MessageSquare, Mail, Send, ChevronDown, ChevronUp } from 'lucide-react';

export default function HelpSupportPanel({ userId, apiUrl }) {
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedFaq, setExpandedFaq] = useState(null);
  const [ticketForm, setTicketForm] = useState({ subject: '', message: '' });
  const [isSubmitting, setIsSubmitting] = useState(false);

  const quickStartGuides = [
    { title: 'Getting Started', icon: '🚀', time: '5 min' },
    { title: 'First Analysis', icon: '📊', time: '3 min' },
    { title: 'Understanding Scores', icon: '⭐', time: '7 min' },
    { title: 'Setting Up Alerts', icon: '🔔', time: '4 min' }
  ];

  const featureGuides = [
    { title: 'Trending Runners', icon: '🔥' },
    { title: 'Auto Discovery', icon: '⚡' },
    { title: 'Watchlist Setup', icon: '📋' },
    { title: 'Premium Features', icon: '👑' }
  ];

  const faqs = [
    {
      q: 'What is Professional Score?',
      a: 'Professional Score is a weighted metric (60% timing, 30% profit, 10% overall position) that measures how early and profitably a wallet enters positions.'
    },
    {
      q: 'How do I read analysis results?',
      a: 'Results show wallets ranked by their entry timing relative to ATH. Look for high "Distance to ATH" scores and consistent performance across multiple tokens.'
    },
    {
      q: 'What are Trending Runners?',
      a: 'Tokens that have pumped 5x+ in the selected timeframe. You can batch analyze them to find wallets that hit multiple runners.'
    },
    {
      q: 'How do Telegram alerts work?',
      a: 'Connect your Telegram in Settings. You\'ll get real-time notifications when monitored wallets buy or sell based on your alert thresholds.'
    },
    {
      q: 'What\'s the difference between Tiers?',
      a: 'S-Tier = Elite (90+ score), A-Tier = Excellent (80-89), B-Tier = Good (70-79), C-Tier = Acceptable (60-69)'
    }
  ];

  const handleSubmitTicket = async () => {
    if (!ticketForm.subject || !ticketForm.message) {
      alert('Please fill in all fields');
      return;
    }

    setIsSubmitting(true);
    try {
      const response = await fetch(`${apiUrl}/api/support/ticket`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          subject: ticketForm.subject,
          message: ticketForm.message
        })
      });

      const data = await response.json();

      if (data.success) {
        alert('✅ Ticket submitted! We\'ll respond within 24 hours.');
        setTicketForm({ subject: '', message: '' });
      } else {
        alert('Failed to submit ticket');
      }
    } catch (error) {
      console.error('Ticket error:', error);
      alert('Error submitting ticket');
    }
    setIsSubmitting(false);
  };

  return (
    <div className="space-y-6">
      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" size={18} />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search help articles..."
          className="w-full bg-black/50 border border-white/10 rounded-lg pl-10 pr-4 py-2 text-sm focus:outline-none focus:border-purple-500"
        />
      </div>

      {/* Quick Start */}
      <div>
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Book className="text-purple-400" size={16} />
          Quick Start
        </h3>
        <div className="grid grid-cols-2 gap-2">
          {quickStartGuides.map((guide, idx) => (
            <button
              key={idx}
              className="p-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-left transition"
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="text-lg">{guide.icon}</span>
                <span className="text-sm font-semibold">{guide.title}</span>
              </div>
              <span className="text-xs text-gray-400">{guide.time} read</span>
            </button>
          ))}
        </div>
      </div>

      {/* Feature Guides */}
      <div>
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          💡 Feature Guides
        </h3>
        <div className="space-y-2">
          {featureGuides.map((guide, idx) => (
            <button
              key={idx}
              className="w-full p-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-left text-sm transition flex items-center gap-2"
            >
              <span>{guide.icon}</span>
              <span>{guide.title}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Video Tutorial */}
      <div className="bg-gradient-to-r from-red-900/20 to-red-800/10 border border-red-500/30 rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Video className="text-red-400" size={16} />
          Video Tutorial
        </h3>
        <button className="w-full px-4 py-2 bg-red-600 hover:bg-red-700 rounded-lg text-sm font-semibold transition flex items-center justify-center gap-2">
          ▶️ Watch 5-Minute Overview
        </button>
      </div>

      {/* FAQs */}
      <div>
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <MessageSquare className="text-blue-400" size={16} />
          Frequently Asked Questions
        </h3>
        <div className="space-y-2">
          {faqs.map((faq, idx) => (
            <div key={idx} className="bg-white/5 border border-white/10 rounded-lg overflow-hidden">
              <button
                onClick={() => setExpandedFaq(expandedFaq === idx ? null : idx)}
                className="w-full p-3 text-left flex items-center justify-between hover:bg-white/5 transition"
              >
                <span className="text-sm font-medium">{faq.q}</span>
                {expandedFaq === idx ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>
              {expandedFaq === idx && (
                <div className="px-3 pb-3 text-sm text-gray-400">
                  {faq.a}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Contact Support */}
      <div className="bg-white/5 border border-white/10 rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Mail className="text-green-400" size={16} />
          Contact Support
        </h3>
        
        <div className="space-y-3 mb-4">
          <a
            href="mailto:support@sifter.io"
            className="flex items-center gap-2 text-sm text-purple-400 hover:text-purple-300"
          >
            📧 support@sifter.io
          </a>
          <a
            href="https://twitter.com/SifterIO"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 text-sm text-purple-400 hover:text-purple-300"
          >
            🐦 @SifterIO
          </a>
          <a
            href="https://t.me/SifterSupport"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 text-sm text-purple-400 hover:text-purple-300"
          >
            💬 t.me/SifterSupport
          </a>
        </div>

        <div className="border-t border-white/10 pt-4">
          <h4 className="text-xs font-semibold mb-2">Submit a Ticket</h4>
          <div className="space-y-2">
            <input
              type="text"
              value={ticketForm.subject}
              onChange={(e) => setTicketForm({...ticketForm, subject: e.target.value})}
              placeholder="Subject"
              className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
            />
            <textarea
              value={ticketForm.message}
              onChange={(e) => setTicketForm({...ticketForm, message: e.target.value})}
              placeholder="Describe your issue..."
              rows={4}
              className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
            />
            <button
              onClick={handleSubmitTicket}
              disabled={isSubmitting}
              className="w-full px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:bg-purple-600/30 rounded-lg text-sm font-semibold transition flex items-center justify-center gap-2"
            >
              {isSubmitting ? (
                <>
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Submitting...
                </>
              ) : (
                <>
                  <Send size={14} />
                  Submit Ticket
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}