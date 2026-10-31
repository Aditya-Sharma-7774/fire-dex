"""Validated request parameters, shared by every route.

This is the trust boundary. Anything a client sends is checked here, before
it reaches a provider, a log line or a language-model prompt.

The symbol rule is the important one. A symbol is placed into every agent's
prompt as the analysis subject, so a free-text symbol was a prompt-injection
path: a newline followed by instructions would have been read by all five
agents. Restricting it to letters and digits removes that path entirely,
rather than trying to detect hostile text after the fact.
"""

from typing import Annotated, Literal

from fastapi import Path
from pydantic import StringConstraints

SYMBOL_PATTERN = r"^[A-Za-z0-9]{1,12}$"
CHAIN_PATTERN = r"^[a-z0-9-]{1,32}$"

# Mirrors SUPPORTED_INTERVALS in app.market.candles; a test keeps them equal.
Interval = Literal["5m", "15m", "1h", "4h", "1d", "1w"]

Symbol = Annotated[str, StringConstraints(strip_whitespace=True, pattern=SYMBOL_PATTERN)]
ChainKey = Annotated[str, StringConstraints(strip_whitespace=True, pattern=CHAIN_PATTERN)]
# Long enough for any real address, short enough that nothing large is echoed
# or decoded. The adapter then validates the exact format for its chain.
Address = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]

SymbolPath = Annotated[
    str, Path(pattern=SYMBOL_PATTERN, description="Token symbol, e.g. 'ETH'")
]
ChainPath = Annotated[
    str, Path(pattern=CHAIN_PATTERN, description="Chain key, e.g. 'ethereum'", examples=["sepolia"])
]
AddressPath = Annotated[
    str,
    Path(max_length=100, description="Public address to query. Never a private key or seed phrase."),
]
