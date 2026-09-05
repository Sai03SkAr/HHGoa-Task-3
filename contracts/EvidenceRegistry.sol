// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title EvidenceRegistry
/// @notice Anchors the Merkle root of a face-match evidence bundle on chain,
///         creating a tamper-evident record that can be re-verified later.
///
/// @dev Deliberately minimal. The sophistication of this project lives in what
///      gets hashed - the canonical evidence bundle - not in Solidity. A larger
///      contract would add attack surface without adding a single guarantee.
///
///      WHAT IS NOT STORED HERE, AND WHY:
///      No face image, no raw embedding, and no personal data of any kind ever
///      reaches this contract. A public chain is permanent and irrevocable, so
///      publishing biometrics to one would be unforgivable and unfixable. The
///      bundle records the embedding only as a salted commitment
///      sha256(salt || embedding), and the salt never leaves the operator's
///      machine. What lands here is a 32-byte root: enough to prove the
///      evidence existed unaltered at a given block, and useless for
///      identifying anyone. That distinction is also what makes erasure
///      coherent - local evidence is deletable, and what remains on chain was
///      never personal data to begin with.
contract EvidenceRegistry {
    struct Anchor {
        bytes32 root;      // Merkle root of the canonical evidence bundle
        string cid;        // optional IPFS CID of the bundle; "" when unpinned
        address submitter;
        uint64 timestamp;  // block time of anchoring
    }

    /// @notice Anchors keyed by their own Merkle root.
    mapping(bytes32 => Anchor) public anchors;

    /// @notice Emitted once per successful anchor. Indexed so a verifier can
    ///         find an anchor from logs alone, without knowing the root.
    event Anchored(
        bytes32 indexed root,
        string cid,
        address indexed submitter,
        uint64 timestamp
    );

    error AlreadyAnchored(bytes32 root);
    error EmptyRoot();

    /// @notice Record `root` on chain. Reverts if it is already present.
    /// @param root Merkle root of the canonical evidence bundle.
    /// @param cid  IPFS CID of the bundle, or "" if it was not pinned.
    ///
    /// @dev Anchors are immutable by construction: there is no update path and
    ///      no owner. Re-anchoring the same root reverts rather than silently
    ///      overwriting the original timestamp, which would destroy the only
    ///      thing the anchor proves - that this evidence existed *by then*.
    function anchor(bytes32 root, string calldata cid) external {
        if (root == bytes32(0)) revert EmptyRoot();
        if (anchors[root].timestamp != 0) revert AlreadyAnchored(root);

        anchors[root] = Anchor({
            root: root,
            cid: cid,
            submitter: msg.sender,
            timestamp: uint64(block.timestamp)
        });

        emit Anchored(root, cid, msg.sender, uint64(block.timestamp));
    }

    /// @notice Look up an anchor.
    /// @return found  Whether `root` has been anchored.
    /// @return record The stored anchor; zero-valued when `found` is false.
    function verify(bytes32 root) external view returns (bool found, Anchor memory record) {
        record = anchors[root];
        found = record.timestamp != 0;
    }
}
