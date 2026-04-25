#!/usr/bin/env node
// 0G Storage helper: stdin JSON command -> stdout JSON result.
//
// Used by Python (shared/zerog.py) to talk to the @0gfoundation/0g-ts-sdk
// without needing a Python ↔ TypeScript bridge.
//
// Commands:
//   {op: "wallet_new"}                   -> {address, private_key}
//   {op: "wallet_info", private_key, evm_rpc?}
//                                        -> {address, balance_eth, balance_wei, chain_id}
//   {op: "merkle_root", data_b64}        -> {root_hash, bytes}
//                                          (offline — no RPC, no signer, no gas)
//   {op: "upload", data_b64, private_key, evm_rpc?, indexer_rpc?}
//                                        -> {root_hash, tx_hash}
//   {op: "download", root_hash, indexer_rpc?}
//                                        -> {data_b64}
//
// All paths return either a result object or {error: "..."} on stderr-style
// failure. Process exit code is 0 for success, 1 for failure.

import { Indexer, MemData } from '@0gfoundation/0g-ts-sdk';
import { ethers } from 'ethers';
import { writeFile, readFile, unlink, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';

const DEFAULT_EVM_RPC = 'https://evmrpc-testnet.0g.ai';
const DEFAULT_INDEXER_RPC = 'https://indexer-storage-testnet-turbo.0g.ai';

function ok(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
}
function fail(msg, extra = {}) {
  process.stdout.write(JSON.stringify({ error: msg, ...extra }) + '\n');
  process.exit(1);
}

async function readStdinJson() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString('utf-8').trim();
  if (!raw) fail('empty stdin — pass a JSON command');
  try {
    return JSON.parse(raw);
  } catch (e) {
    fail(`invalid JSON on stdin: ${e.message}`);
  }
}

// ─────────────── ops ───────────────

async function opWalletNew() {
  const w = ethers.Wallet.createRandom();
  ok({
    address: w.address,
    private_key: w.privateKey,
    mnemonic: w.mnemonic ? w.mnemonic.phrase : null,
  });
}

async function opWalletInfo({ private_key, evm_rpc }) {
  if (!private_key) fail("missing 'private_key'");
  const provider = new ethers.JsonRpcProvider(evm_rpc || DEFAULT_EVM_RPC);
  const signer = new ethers.Wallet(private_key, provider);
  const [bal, network] = await Promise.all([
    provider.getBalance(signer.address),
    provider.getNetwork(),
  ]);
  ok({
    address: signer.address,
    balance_wei: bal.toString(),
    balance_eth: ethers.formatEther(bal),
    chain_id: Number(network.chainId),
  });
}

async function opMerkleRoot({ data_b64 }) {
  if (!data_b64) fail("missing 'data_b64'");
  const data = Buffer.from(data_b64, 'base64');
  const view = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  const file = new MemData(view);
  const [tree, treeErr] = await file.merkleTree();
  if (treeErr !== null) fail(`merkleTree failed: ${treeErr?.message ?? treeErr}`);
  ok({
    root_hash: tree.rootHash(),
    bytes: data.byteLength,
  });
}

async function opUpload({ data_b64, private_key, evm_rpc, indexer_rpc }) {
  if (!data_b64) fail("missing 'data_b64'");
  if (!private_key) fail("missing 'private_key'");

  const data = Buffer.from(data_b64, 'base64');
  const provider = new ethers.JsonRpcProvider(evm_rpc || DEFAULT_EVM_RPC);
  const signer = new ethers.Wallet(private_key, provider);

  // 0G's MemData accepts ArrayLike<number>. A Uint8Array view of the buffer works.
  const view = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  const file = new MemData(view);

  const [tree, treeErr] = await file.merkleTree();
  if (treeErr !== null) fail(`merkleTree failed: ${treeErr?.message ?? treeErr}`);
  const rootHash = tree.rootHash();

  const indexer = new Indexer(indexer_rpc || DEFAULT_INDEXER_RPC);
  const [tx, uploadErr] = await indexer.upload(file, evm_rpc || DEFAULT_EVM_RPC, signer);
  if (uploadErr !== null) fail(`upload failed: ${uploadErr?.message ?? uploadErr}`, { root_hash: rootHash });

  ok({
    root_hash: rootHash,
    tx_hash: typeof tx === 'string' ? tx : tx?.hash ?? String(tx),
    bytes_uploaded: data.byteLength,
  });
}

async function opDownload({ root_hash, indexer_rpc }) {
  if (!root_hash) fail("missing 'root_hash'");
  const indexer = new Indexer(indexer_rpc || DEFAULT_INDEXER_RPC);
  const tmpDir = tmpdir();
  const outPath = join(tmpDir, `zg-dl-${randomUUID()}.bin`);

  const err = await indexer.download(root_hash, outPath, true);
  if (err !== null) fail(`download failed: ${err?.message ?? err}`);

  const data = await readFile(outPath);
  await unlink(outPath).catch(() => {});
  ok({
    root_hash,
    data_b64: data.toString('base64'),
    bytes_downloaded: data.byteLength,
  });
}

// ─────────────── main ───────────────

const cmd = await readStdinJson();
const op = cmd.op;

try {
  if (op === 'wallet_new') await opWalletNew();
  else if (op === 'wallet_info') await opWalletInfo(cmd);
  else if (op === 'merkle_root') await opMerkleRoot(cmd);
  else if (op === 'upload') await opUpload(cmd);
  else if (op === 'download') await opDownload(cmd);
  else fail(`unknown op: ${op}`);
} catch (e) {
  fail(`unhandled exception: ${e?.message ?? e}`, { stack: e?.stack });
}
