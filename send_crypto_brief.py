import sys
sys.path.insert(0, 'C:\\projects\\ai-agent-platform\\mind-clone')
from src.mind_clone.services.telegram.messaging import send_telegram_message

msg = """**Crypto Brief — June 25, 2025**

1. **BTC Dips to ~$66K** — Oil hit 3-yr high above $105, US-Iran tensions pressured BTC. Whale selling cooled, $59K key support.

2. **Stablecoins to Hit $2T** — Standard Chartered says turnover doubled in 2 years (AI/TradFi). Keyrock hit $1.1B valuation (SC Ventures-led Series C).

3. **ETH L2s Consolidate** — Ethereum builders proposed Economic Zone to unify fragmented L2s. Coinbase Base upgrading for AI agents.

4. **AI Agent Security Risk** — CertiK warns OpenClaw can drain wallets via malicious skills. axios npm also compromised.

BTC: $67,400 | ETH: $2,074 | Market Cap: $2.41T
BTC dominance: 56.2% | ETH: 10.4%"""

send_telegram_message(msg)
print('Sent!')
