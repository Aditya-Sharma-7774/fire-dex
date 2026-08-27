"""The ChainAdapter contract.

This is the abstraction that lets Fire DEX support technically different
blockchains without the rest of the application knowing the difference.

Everything above this layer asks for "the native balance of this address
on this chain". Whether that means an account balance on Ethereum, a
lamport balance on Solana, or the sum of unspent outputs on Bitcoin is the
adapter's problem, not the caller's.

We use typing.Protocol rather than an abstract base class because it gives
structural typing: an adapter simply has to have the right methods, it
does not have to inherit from anything. That keeps each adapter free to be
constructed however its chain requires.
"""

from typing import Protocol, runtime_checkable

from app.blockchain.types import ChainConfig, ChainStatus, NativeBalance


@runtime_checkable
class ChainAdapter(Protocol):
    """What every chain implementation must be able to do."""

    @property
    def config(self) -> ChainConfig:
        """The chain this adapter is bound to."""
        ...

    def validate_address(self, address: str) -> str:
        """Check the address is valid for THIS chain and return it normalised.

        Must raise InvalidAddressError rather than returning a flag, so a
        bad address can never accidentally be passed on to an RPC call.

        Returns the canonical form -- for EVM chains that means the EIP-55
        checksummed version.
        """
        ...

    async def get_native_balance(self, address: str) -> NativeBalance:
        """Balance of the chain's own asset (ETH, BNB, SOL, BTC)."""
        ...

    async def get_status(self) -> ChainStatus:
        """Whether this chain is configured and its node is reachable."""
        ...
