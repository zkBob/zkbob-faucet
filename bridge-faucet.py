#!/usr/bin/env python3

from json import load, dump
from web3 import Web3, HTTPProvider
from web3.middleware import geth_poa_middleware
from eth_account import Account
from time import sleep
from os import getenv
from dotenv import load_dotenv
from logging import basicConfig, info, INFO
from statistics import median, mean

basicConfig(level=INFO)

STOP_FILE = 'stop.tmp'

dotenv_read = False

while True: 
    ZKBOB_RPC = getenv('ZKBOB_RPC', 'https://polygon-rpc.com')
    HISTORY_BLOCK_RANGE = int(getenv('HISTORY_BLOCK_RANGE', 10000))

    BOB_TOKEN = getenv('BOB_TOKEN', '0xB0B195aEFA3650A6908f15CdaC7D92F8a5791B0B')
    POOL_CONTRACT = getenv('POOL_CONTRACT', '0x72e6B59D4a90ab232e55D4BB7ed2dD17494D62fB')

    FAUCET_PRIVKEY = getenv('FAUCET_PRIVKEY', None)

    GAS_PRICE = float(getenv('GAS_PRICE', -1))
    HISTORICAL_BASE_FEE_DEPTH = int(getenv('HISTORICAL_BASE_FEE_DEPTH', 20))
    BASE_FEE_RATIO = float(getenv('BASE_FEE_RATIO', 1.3))
    FEE_LIMIT = float(getenv('FEE_LIMIT', 150))

    GAS_LIMIT = int(getenv('GAS_LIMIT', 30000))
    REWARD = float(getenv('REWARD', 0.1))
    POLLING_INTERVAL = getenv('POLLING_INTERVAL', 60)

    #INITIAL_START_BLOCK = 33709535
    INITIAL_START_BLOCK = int(getenv('INITIAL_START_BLOCK', 0))
    FINALIZATION_INTERVAL = int(getenv('FINALIZATION_INTERVAL', 128)) # blocks

    JSON_DB_DIR = getenv('JSON_DB_DIR', '.')
    JSON_START_BLOCK = getenv('JSON_START_BLOCK', 'faucet-start-block.json')
    JSON_CONTRACTS = getenv('JSON_CONTRACTS', 'polygon-contracts.json')

    TEST_TO_SEND = getenv('TEST_TO_SEND', False)

    if not FAUCET_PRIVKEY:
        if dotenv_read:
            break

        info('Environment is not configured')
        load_dotenv('./.env')
        dotenv_read = True
    else: 
        break

if not FAUCET_PRIVKEY:
    raise BaseException("Faucet's privkey is not provided. Check the configuration")

info(f'ZKBOB_RPC = {ZKBOB_RPC}')
info(f'HISTORY_BLOCK_RANGE = {HISTORY_BLOCK_RANGE}')
info(f'BOB_TOKEN = {BOB_TOKEN}')
info(f'POOL_CONTRACT = {POOL_CONTRACT}')
info(f'FAUCET_PRIVKEY = ...')
info(f'GAS_PRICE = {GAS_PRICE}')
info(f'HISTORICAL_BASE_FEE_DEPTH = {HISTORICAL_BASE_FEE_DEPTH}')
info(f'BASE_FEE_RATIO = {BASE_FEE_RATIO}')
info(f'FEE_LIMIT = {FEE_LIMIT}')
info(f'GAS_LIMIT = {GAS_LIMIT}')
info(f'REWARD = {REWARD}')
info(f'POLLING_INTERVAL = {POLLING_INTERVAL}')
info(f'INITIAL_START_BLOCK = {INITIAL_START_BLOCK}')
info(f'FINALIZATION_INTERVAL = {FINALIZATION_INTERVAL}')
info(f'JSON_DB_DIR = {JSON_DB_DIR}')
info(f'JSON_START_BLOCK = {JSON_START_BLOCK}')
info(f'JSON_CONTRACTS = {JSON_CONTRACTS}')
info(f'TEST_TO_SEND = {TEST_TO_SEND}')

# event
# event Transfer(address indexed from, address indexed to, uint256 value)
ABI = """
{
   "anonymous":false,
   "inputs":[
      {
         "indexed":true,
         "internalType":"address",
         "name":"from",
         "type":"address"
      },
      {
         "indexed":true,
         "internalType":"address",
         "name":"to",
         "type":"address"
      },
      {
         "indexed":false,
         "internalType":"uint256",
         "name":"value",
         "type":"uint256"
      }
   ],
   "name":"Transfer",
   "type":"event"
}
"""

plg_w3 = Web3(HTTPProvider(ZKBOB_RPC))
plg_w3.middleware_onion.inject(geth_poa_middleware, layer=0)

plg_chainId = plg_w3.eth.chain_id

bob_token = plg_w3.eth.contract(abi = ABI, address = BOB_TOKEN)

faucet = Account.privateKeyToAccount(FAUCET_PRIVKEY)

sending_tested = False

try:
    with open(f'{JSON_DB_DIR}/{JSON_START_BLOCK}') as f:
      tmp = load(f)
      start_block = int(tmp['start_block'])
except IOError:
    info("no start block stored previously")
    start_block = INITIAL_START_BLOCK
info(f'start block: {start_block}')

while True:
    try:
        with open(f'{JSON_DB_DIR}/{STOP_FILE}') as f:
            info("Stopping faucet")
            break
    except IOError:
        pass

    try:
        last_block = plg_w3.eth.getBlock('latest').number
    except:
        raise BaseException('Cannot get the latest block number')
    info(f'current last block: {last_block}')
    last_block = last_block - FINALIZATION_INTERVAL
    if start_block < last_block - HISTORY_BLOCK_RANGE:
        start_block = last_block - HISTORY_BLOCK_RANGE
        info(f'start block is too deep, new start block: {start_block}')

    event_filter = bob_token.events.Transfer.build_filter()
    event_filter.indexed_args[0].match_single(POOL_CONTRACT)

    info(f'Looking for Transfer events on BOB token from {start_block} to {last_block}')
    try:
        bob_logs = plg_w3.eth.getLogs({'fromBlock': start_block, 
                                        'toBlock': last_block, 
                                        'address': event_filter.address, 
                                        'topics': event_filter.topics})
    except:
        raise BaseException('Cannot get BOB token logs')
    info(f'Found {len(bob_logs)} Transfer events on BOB token')
    
    recipients = set()

    for log in bob_logs:
        recipient = bob_token.events.Transfer().processLog(log).args.to
        recipients.add(recipient)
    info(f'Identified {len(recipients)} tokens recipients from BOB token events')

    try:
        with open(f'{JSON_DB_DIR}/{JSON_CONTRACTS}') as f:
          contracts = load(f)
    except IOError:
        info("no contracts identified previously")
        contracts = {}

    endowing = []
    if TEST_TO_SEND and not sending_tested:
        endowing.append(faucet.address)
        info(f'activated testmode to send a transaction')
        sending_tested = True

    for recipient in recipients:
        if recipient in contracts:
            continue
        code = plg_w3.eth.getCode(recipient)
        if code != b'':
            contracts[recipient] = True
            continue
        balance = plg_w3.eth.getBalance(recipient)
        if balance == 0:
            info(f'{recipient} balance is zero')
            endowing.append(recipient)
    info(f'found {len(endowing)} accounts for reward')
    
    with open(f'{JSON_DB_DIR}/{JSON_CONTRACTS}', 'w') as json_file:
      dump(contracts, json_file)
    
    balance_error = False
    
    if len(endowing) > 0:
        try:
            faucet_balance = plg_w3.eth.getBalance(faucet.address)
        except:
            raise BaseException("Cannot get faucet balance")
        info(f'faucet balance: {faucet_balance}')

        if GAS_PRICE < 0:
            try:
                fee_hist = plg_w3.eth.fee_history(HISTORICAL_BASE_FEE_DEPTH, last_block, [5, 30])
            except:
                raise BaseException("Cannot get historical fee data")

            base_fee_hist = fee_hist.baseFeePerGas
            historical_base_fee = max(int(median(base_fee_hist)), int(mean(base_fee_hist)))
            info(f'Base fee based on historical data: {Web3.fromWei(historical_base_fee, "wei")}')

            priority_fee = [ mean(i) for i in fee_hist.reward ]
            recommended_priority_fee = min(int(mean(priority_fee)), int(median(priority_fee)))

            max_gas_price = min(int(historical_base_fee * BASE_FEE_RATIO) + recommended_priority_fee, 
                                Web3.toWei(FEE_LIMIT, 'gwei'))
            info(f'Suggested max fee per gas: {Web3.fromWei(max_gas_price, "gwei")}')
            info(f'Suggested priority fee per gas: {Web3.fromWei(recommended_priority_fee, "gwei")}')
        else:
            max_gas_price = Web3.toWei(GAS_PRICE, 'gwei')
    
        if faucet_balance > len(endowing) * GAS_LIMIT * max_gas_price:
            try:
                nonce = plg_w3.eth.getTransactionCount(faucet.address)
            except:
                raise BaseException("Cannot get transactions count of faucet's account")
            info(f'starting nonce: {nonce}')
            for recipient in endowing:
                tx = {
                    'nonce': nonce,
                    'gas': GAS_LIMIT,
                    'data': b'Rewarded for zkBOB withdrawal',
                    'chainId': plg_chainId,
                    'value': Web3.toWei(REWARD, 'ether'),
                    'to': recipient,
                }
                if GAS_PRICE < 0:
                    tx['maxFeePerGas'] = max_gas_price
                    tx['maxPriorityFeePerGas'] = recommended_priority_fee
                else:
                    tx['gasPrice'] = max_gas_price
                rawtx = faucet.signTransaction(tx)
                sent_tx_hash = plg_w3.eth.sendRawTransaction(rawtx.rawTransaction)
                info(f'{recipient} rewarded by {Web3.toHex(sent_tx_hash)}')
                nonce += 1
                sleep(0.1)
        else:
            info(f'not enough balance on the faucet {faucet.address}')
            balance_error = True

    if not balance_error:
        start_block = last_block + 1
        with open(f'{JSON_DB_DIR}/{JSON_START_BLOCK}', 'w') as json_file:
            dump({'start_block': start_block}, json_file)
            
    sleep(POLLING_INTERVAL)