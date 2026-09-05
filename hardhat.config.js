// Minimal Hardhat config. Its ONLY job is `npx hardhat node` - a persistent
// local chain on 127.0.0.1:8545 so `run` and `verify` can be separate
// processes without needing testnet funds.
//
// Contracts are compiled by py-solc-x from Python, not by Hardhat - see
// docs/DECISIONS.md D-014. Nothing in the Python pipeline depends on this file.
export default {
  solidity: "0.8.24",
};
