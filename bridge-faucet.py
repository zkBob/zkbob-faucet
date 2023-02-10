#!/usr/bin/env python3

from json import load, dump, loads
import ast

from web3 import Web3, HTTPProvider
from web3.middleware import geth_poa_middleware
from web3.exceptions import TransactionNotFound

from eth_account import Account

from time import sleep

from os import getenv
from dotenv import load_dotenv

from logging import basicConfig, info, error, warning, INFO

from statistics import median, mean

basicConfig(level=INFO)

STOP_FILE = 'stop.tmp'

dotenv_read = False

while True: 
    ZKBOB_RPC = getenv('ZKBOB_RPC', 'https://rpc.ankr.com/polygon')
    RPC_LIMIT_BLOCK_RANGE = int(getenv('RPC_LIMIT_BLOCK_RANGE', 3000))
    HISTORY_BLOCK_RANGE = int(getenv('HISTORY_BLOCK_RANGE', 3000))
    BLOCKS_TO_WAIT_BEFORE_RETRY = int(getenv('BLOCKS_TO_WAIT_BEFORE_RETRY', 300))

    BOB_TOKEN = getenv('BOB_TOKEN', '0xB0B195aEFA3650A6908f15CdaC7D92F8a5791B0B')
    POOL_CONTRACT = getenv('POOL_CONTRACT', '0x72e6B59D4a90ab232e55D4BB7ed2dD17494D62fB')
    WITHDRAWAL_THRESHOLD = float(getenv('WITHDRAWAL_THRESHOLD', 10))

    FAUCET_PRIVKEY = getenv('FAUCET_PRIVKEY', None)

    GAS_PRICE = float(getenv('GAS_PRICE', -1))
    HISTORICAL_BASE_FEE_DEPTH = int(getenv('HISTORICAL_BASE_FEE_DEPTH', 20))
    BASE_FEE_RATIO = float(getenv('BASE_FEE_RATIO', 1.3))
    FEE_LIMIT = float(getenv('FEE_LIMIT', 150))

    GAS_LIMIT = int(getenv('GAS_LIMIT', 30000))
    REWARD = float(getenv('REWARD', 0.1))
    POLLING_INTERVAL = int(getenv('POLLING_INTERVAL', 60))

    INITIAL_START_BLOCK = int(getenv('INITIAL_START_BLOCK', 33709535))
    FINALIZATION_INTERVAL = int(getenv('FINALIZATION_INTERVAL', 128)) # blocks

    JSON_DB_DIR = getenv('JSON_DB_DIR', '.')
    JSON_HISTORY = getenv('JSON_HISTORY', 'faucet-history.json')
    JSON_CONTRACTS = getenv('JSON_CONTRACTS', 'polygon-contracts.json')

    WEB3_RETRY_ATTEMPTS = int(getenv('WEB3_RETRY_ATTEMPTS', 2))
    WEB3_RETRY_DELAY = int(getenv('WEB3_RETRY_DELAY', 5))

    TEST_TO_SEND = getenv('TEST_TO_SEND', False)

    if TEST_TO_SEND == 'true' or TEST_TO_SEND == 'True':
        TEST_TO_SEND = True
    else:
        TEST_TO_SEND = False

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
info(f'RPC_LIMIT_BLOCK_RANGE = {RPC_LIMIT_BLOCK_RANGE}')
info(f'HISTORY_BLOCK_RANGE = {HISTORY_BLOCK_RANGE}')
info(f'BLOCKS_TO_WAIT_BEFORE_RETRY = {BLOCKS_TO_WAIT_BEFORE_RETRY}')
info(f'BOB_TOKEN = {BOB_TOKEN}')
info(f'POOL_CONTRACT = {POOL_CONTRACT}')
info(f'WITHDRAWAL_THRESHOLD = {WITHDRAWAL_THRESHOLD}')
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
info(f'JSON_HISTORY = {JSON_HISTORY}')
info(f'JSON_CONTRACTS = {JSON_CONTRACTS}')
info(f'WEB3_RETRY_ATTEMPTS = {WEB3_RETRY_ATTEMPTS}')
info(f'WEB3_RETRY_DELAY = {WEB3_RETRY_DELAY}')
info(f'TEST_TO_SEND = {TEST_TO_SEND}')

if HISTORY_BLOCK_RANGE > RPC_LIMIT_BLOCK_RANGE:
    raise BaseException("History block range cannot be greater than RPC limit block range")

# event
# event Transfer(address indexed from, address indexed to, uint256 value)
ABI = """
[
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
]
"""

plg_w3 = Web3(HTTPProvider(ZKBOB_RPC))
plg_w3.middleware_onion.inject(geth_poa_middleware, layer=0)

plg_chainId = plg_w3.eth.chain_id

bob_token = plg_w3.eth.contract(abi = ABI, address = BOB_TOKEN)
event_filter = bob_token.events.Transfer.build_filter()
event_filter.indexed_args[0].match_single(POOL_CONTRACT)
token = {
    'cnt': bob_token,
    'efilter': event_filter,
    'handler': bob_token.events.Transfer().processLog
}

faucet = Account.privateKeyToAccount(FAUCET_PRIVKEY)

sending_tested = False

# Loads data stored by previous run of the main loop
# If it is the very first run, the data is initialized with default values
def get_storage_of_handled():
    try:
        with open(f'{JSON_DB_DIR}/{JSON_HISTORY}') as f:
            storage = load(f)
            previous_last_block = int(storage['last_block'])
            handled_recipients = storage['history']
            nonces = storage['nonces']
            info(f'Found last monitored block: {previous_last_block} and have {len(handled_recipients)} historical records')
    except IOError:
        previous_last_block = INITIAL_START_BLOCK
        handled_recipients = {}
        nonces = {}
        warning(f'no historical records found, suggesting discovery from {previous_last_block} block')
    return previous_last_block, handled_recipients, nonces

# Stores the data after the latest run of the main loop
def save_storage_of_handled(_observation_range, _handled_recipients, _nonces):
    info(f'Storing new bunch of historical records {len(_handled_recipients)} and last monitored block {_observation_range[1]}')
    with open(f'{JSON_DB_DIR}/{JSON_HISTORY}', 'w') as json_file:
        dump({'last_block': _observation_range[1], 
              'history': _handled_recipients,
              'nonces': _nonces
             }, json_file)

# Call a web3 method with consequent retries if the call fails
# It is possible to pass a list of exceptions which will not cause a retry
def make_web3_call_with_exceptions(func, exceptions, *args, **kwargs):
    attempts = 0
    exc = None
    while attempts < WEB3_RETRY_ATTEMPTS:
        if len(exceptions) > 0:
            try:
                return func(*args, **kwargs)
            except tuple(exceptions) as e:
                raise e
            except Exception as e:
                error(f'Not able to get data')
                exc = e
        else:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error(f'Not able to get data')
                exc = e                
        attempts += 1
        info(f'Repeat attempt in {WEB3_RETRY_DELAY} seconds')
        sleep(WEB3_RETRY_DELAY)
    raise exc

# Wrapper to call a web3 method without ability to catch specific exceptions 
def make_web3_call(func, *args, **kwargs):
    return make_web3_call_with_exceptions(func, [], *args, **kwargs)

# Returns range of blocks to look for events.
# Default limit finishes by the last finalized block and starts
# HISTORY_BLOCK_RANGE block lower
def get_observation_range(_previous_last_block):
    last_block = make_web3_call(plg_w3.eth.getBlock, 'latest').number
    last_block = last_block - FINALIZATION_INTERVAL
    if _previous_last_block > last_block:
        BaseException("Last block received from RPC is less than last revisited block")
    # If the previous block is outside of range that allowed by the RPC provider
    # it is necessary to reduce the right limit of the lookup range 
    if (_previous_last_block + 1 + RPC_LIMIT_BLOCK_RANGE) < last_block:
        start_block = _previous_last_block + 1
        last_block = _previous_last_block + 1 + RPC_LIMIT_BLOCK_RANGE
    else:
        # If the previous block is lower the default range, extende the range to explore 
        # events in the blocks after the previous block
        if last_block - (_previous_last_block + 1) > HISTORY_BLOCK_RANGE:
            start_block = _previous_last_block + 1
        else:
            start_block = last_block - HISTORY_BLOCK_RANGE
    info(f'Suggested range of blocks: {start_block} - {last_block}')
    return start_block, last_block

# Parse a transaction log and extract a recipient of BOB tokens
# if value of the transfer is less the threshold recipient will be discarded
def process_event(_token, _event):
    pl = _token['handler'](_event)
    recipient = pl.args['to']
    value = pl.args['value']
    if value >= Web3.toWei(WITHDRAWAL_THRESHOLD, "ether"):
        return recipient
    else:
        return None

# Recives Transfer events from the range of blocks and returns list of BOB token recipients with
# transfer values above threshold
def get_recipients(_token, _from_block, _to_block):
    event_name = _token['efilter'].event_abi['name']
    info(f'Looking for {event_name} events on BOB token from {_from_block} to {_to_block}')
    events = make_web3_call(_token['cnt'].web3.eth.getLogs, {'fromBlock': _from_block, 
                                                             'toBlock': _to_block, 
                                                             'address': _token['efilter'].address, 
                                                             'topics': _token['efilter'].topics})
    len_events = len(events)
    info(f"Found {len_events} of {event_name} events")
    if len_events > 0:
        recipients = set([process_event(_token, e) for e in events])
        recipients.discard(None)
    else:
        recipients = set()
    info(f'Identified {len(recipients)} tokens recipients from BOB token events')

    return recipients

# Returns the list of recipients discovered in the past but with unsucessfull rewards
def revisit_previous_rewards(handled_recipients, observation_range):
    # Discover transactions with rewards made in the past.
    # The range of blocks where reward attempts were made is
    # limited by HISTORY_BLOCK_RANGE + BLOCKS_TO_WAIT_BEFORE_RETRY earlier the last block 
    # from left side and BLOCKS_TO_WAIT_BEFORE_RETRY earlier the last block from the right side
    accounts_to_check = {}
    for block in list(handled_recipients.keys()):
        if int(block) >= observation_range[1] - (HISTORY_BLOCK_RANGE + BLOCKS_TO_WAIT_BEFORE_RETRY):
            if int(block) < observation_range[1] - BLOCKS_TO_WAIT_BEFORE_RETRY:
                for account in handled_recipients[block]:
                    if not account in accounts_to_check:
                        accounts_to_check[account] = []
                    # Since the same account can be tried to be rewarded several times
                    # collect transactions of all attempts
                    accounts_to_check[account].append(handled_recipients[block][account])
        else:
            del handled_recipients[block]
    info(f'Identified {len(accounts_to_check)} candidates to check sent rewards')

    candidates_for_retry = set()
    for account in accounts_to_check:
        reward_sent = False
        # Check all the transactions made for the account
        # If at least one transaction is successfull, don't include
        # the account for re-try attemtps
        for txhash in accounts_to_check[account]:
            info(f'Check status of tx {txhash} sent to reward {account}')
            try:
                rcpt = make_web3_call_with_exceptions(plg_w3.eth.get_transaction_receipt, [TransactionNotFound], txhash)
            except TransactionNotFound:
                info(f'Tx {txhash} not found')
            except Exception as e:
                raise e
            else:
                info(f'Tx {txhash} mined sucessfully')
                if rcpt.blockNumber:
                    reward_sent = True
        if not reward_sent:
            candidates_for_retry.add(Web3.toChecksumAddress(account))
    info(f'Identified {len(candidates_for_retry)} accounts to re-send rewards')
            
    return candidates_for_retry

# Filters out recipients to be rewarded
def soap_recipients(_recipients, _handled_recipients, _observation_range):
    # Get a list of recipients which were handled
    # recently - not deeper than BLOCKS_TO_WAIT_BEFORE_RETRY 
    handled_recently = set()
    for block in list(_handled_recipients.keys()):
        if int(block) >= _observation_range[1] - BLOCKS_TO_WAIT_BEFORE_RETRY:
            handled_recently.update([account for account in _handled_recipients[block]])

    # Open a cache with contracts used as recipients in the past
    try:
        with open(f'{JSON_DB_DIR}/{JSON_CONTRACTS}') as f:
            contracts = load(f)
    except IOError:
        info("no contracts identified previously")
        contracts = {}

    endowing = set()
    # Special case to add the facet address as the reward recipient to test transactions sending
    if TEST_TO_SEND and not sending_tested:
        endowing.append(faucet.address)
        info(f'activated testmode to send a transaction')
        sending_tested = True

    contracts_cache_updated = False
    # Filter rules:
    # - recipient must not be a contract
    # - there is no attempts to send reward recent BLOCKS_TO_WAIT_BEFORE_RETRY blocks
    # - recipient's balance of native tokens is zero
    for recipient in _recipients:
        # check if the contract by using the cache
        if recipient in contracts:
            info(f'{recipient} is contract. Skipping')
            continue
        # the address was not found in the cache, request the RPC provider
        # The last block is used to make sure that RPC provider is synchronized: doesn't
        # outdated provide data 
        code = make_web3_call(plg_w3.eth.getCode, recipient, _observation_range[1])
        if code != b'':
            contracts[recipient] = True
            contracts_cache_updated = True
            info(f'{recipient} is contract. Skipping')
            continue
        # check if there is not attempts to send reward recently
        if recipient in handled_recently:
            info(f'{recipient} has been handled recently. Skipping')
            continue
        # check that the recipient's balance is zero
        # The last block is used to make sure that RPC provider is synchronized: doesn't
        # outdated provide data 
        balance = make_web3_call(plg_w3.eth.getBalance, recipient, _observation_range[1])
        if balance == 0 or recipient == faucet.address:
            info(f'{recipient} balance is zero')
            endowing.add(recipient)
        else:
            info(f'Balance of {recipient} is not zero. Skipping')
    info(f'found {len(endowing)} accounts for reward')
    
    # Update the cache with contracts
    if contracts_cache_updated:
        with open(f'{JSON_DB_DIR}/{JSON_CONTRACTS}', 'w') as json_file:
            dump(contracts, json_file)
        
    return endowing

# Tries to predict gas price based on the choosen apporach
def estimate_gas_price():    
    if GAS_PRICE < 0:
        # For Type 2 transactions
        
        # It makes sense to look at very last block rather than finalized block
        last_block = make_web3_call(plg_w3.eth.getBlock, 'latest').number

        fee_hist = make_web3_call(plg_w3.eth.fee_history, HISTORICAL_BASE_FEE_DEPTH, last_block, [5, 30])

        # Predict base fee by getting base fees of recent blocks
        base_fee_hist = fee_hist.baseFeePerGas
        historical_base_fee = max(int(median(base_fee_hist)), int(mean(base_fee_hist)))
        info(f'Base fee based on historical data: {Web3.fromWei(historical_base_fee, "wei")}')

        # Predict priority fee by getting mean of priority fees from every recent block
        priority_fee = [ mean(i) for i in fee_hist.reward ]
        recommended_priority_fee = min(int(mean(priority_fee)), int(median(priority_fee)))

        max_gas_price = min(int(historical_base_fee * BASE_FEE_RATIO) + recommended_priority_fee, 
                            Web3.toWei(FEE_LIMIT, 'gwei'))
        info(f'Suggested max fee per gas: {Web3.fromWei(max_gas_price, "gwei")}')
        info(f'Suggested priority fee per gas: {Web3.fromWei(recommended_priority_fee, "gwei")}')
    else:
        # For legacy transactions
        max_gas_price = Web3.toWei(GAS_PRICE, 'gwei')
        recommended_priority_fee = 0
        
    return max_gas_price, recommended_priority_fee

# Adjusts gas price for the case if a transaction with the same nonce was already sent but stuck
# by some reason. RPC providers expect a replacing transaction with higher gas price that was
# in the existing one
def adjust_gas_price(_current_gas_price, _previous_gas_price):
    increased_max_gas_price = int(_previous_gas_price[0] * 1.1) + 1
    max_gas_price = min(max(_current_gas_price[0], increased_max_gas_price),
                        Web3.toWei(FEE_LIMIT, 'gwei'))
    if _previous_gas_price[1] != 0:
        increased_recommended_priority_fee = int(_previous_gas_price[1] * 1.1) + 1
        recommended_priority_fee = max(_current_gas_price[1], 
                                       increased_recommended_priority_fee)
    else:
        recommended_priority_fee = 0
    return max_gas_price, recommended_priority_fee

# Sends signed transaction
# Tries to handle RPC responses caused by traffic conjections or synchronization issues
def sent_raw_transaction(_rawtx):
    try:
        sent_tx_hash = make_web3_call_with_exceptions(plg_w3.eth.sendRawTransaction, [ValueError], _rawtx.rawTransaction)
    except ValueError as ve:
        ve_as_str = str(ve)
        try:
            exc_dict = ast.literal_eval(ve_as_str)
        except Exception as pars_e:
            error(f'Cannot parse "{ve_as_str}"')
            raise pars_e
        else:
            # Tries to parse the response
            if not 'message' in exc_dict:
                error(f'No message text in {ve_as_str}')
                raise ve
            ret_message = exc_dict['message']
            warning(f'During tx sending "{ret_message}" returned by RPC')
            # For all cases except listed throw an error
            if not ret_message in ['nonce too low',
                                   'already known',
                                   'replacement transaction underpriced', 
                                   'INTERNAL_ERROR: could not replace existing tx']:
                raise ve
            info(f'{recipient} marked as handled to evaluate reward re-sending later')
            return Web3.toHex(_rawtx.hash)
    str_hash = Web3.toHex(sent_tx_hash)
    info(f'{recipient} rewarded by {str_hash}')
    return str_hash

while True:
    # If a stop files exists, stop the faucet.
    # It will not work if the faucet is run within the docker
    # with the option "restart: unless-stopped"
    try:
        with open(f'{JSON_DB_DIR}/{STOP_FILE}') as f:
            info("Stopping faucet")
            break
    except IOError:
        pass

    previous_last_block, handled_recipients, nonces = get_storage_of_handled()

    observation_range = get_observation_range(previous_last_block)

    recipients = get_recipients(token, observation_range[0], observation_range[1])

    recipients.update(revisit_previous_rewards(handled_recipients, observation_range))

    endowing = soap_recipients(recipients, handled_recipients, observation_range)

    balance_error = False
    if len(endowing) > 0:
        # Get the current balance of the faucet to avoid attempts
        # to send rewards when the faucet has no funds
        faucet_balance = make_web3_call(plg_w3.eth.getBalance, faucet.address)
        info(f'faucet balance: {faucet_balance}')

        max_gas_price, recommended_priority_fee = estimate_gas_price()

        # Check if the faucet has enough funds to send all discovered rewards
        if faucet_balance > len(endowing) * GAS_LIMIT * max_gas_price:
            update_for_handled_recipients = {}

            nonce = make_web3_call(plg_w3.eth.getTransactionCount, faucet.address)
            # Since a new nonce received remove old records from the gas prices history log
            for existing_nonce in list(nonces):
                if int(existing_nonce) < nonce:
                    del nonces[existing_nonce]
            info(f'starting nonce: {nonce}')

            for recipient in endowing:
                str_nonce = str(nonce)
                # if exists a record in the gas price history log it means that the faucet
                # already tried to send a transaction with the same nonce
                # in order to avoid getting 'replacement transaction underpriced' RPC error
                # it is necessary to adjust the estimated gas price
                if str_nonce in nonces:
                    tx_max_gas_price, tx_recommended_priority_fee = adjust_gas_price([max_gas_price, recommended_priority_fee], 
                                                                                    nonces[str_nonce])
                    
                tx = {
                    'nonce': nonce,
                    'gas': GAS_LIMIT,
                    'data': b'Rewarded for zkBOB withdrawal',
                    'chainId': plg_chainId,
                    'value': Web3.toWei(REWARD, 'ether'),
                    'to': recipient,
                }
                if GAS_PRICE < 0:
                    tx['maxFeePerGas'] = tx_max_gas_price
                    tx['maxPriorityFeePerGas'] = tx_recommended_priority_fee
                else:
                    tx['gasPrice'] = tx_max_gas_price
                    
                rawtx = faucet.signTransaction(tx)
                sent_tx_hash = sent_raw_transaction(rawtx)
                # Record the attempt to send the reward
                update_for_handled_recipients[recipient] = sent_tx_hash
                # Store values for gas price used in the transaction with current nonce
                nonces[str_nonce] = [tx_max_gas_price, tx_recommended_priority_fee]
                
                nonce += 1
                sleep(0.1)
            # Store all reward attempts made after events observation limited by the lates block
            handled_recipients[str(observation_range[1])] = update_for_handled_recipients
        else:
            error(f'not enough balance on the faucet {faucet.address}')
            balance_error = True

    if not balance_error:
        save_storage_of_handled(observation_range, handled_recipients, nonces)
            
    sleep(POLLING_INTERVAL)