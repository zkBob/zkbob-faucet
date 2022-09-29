zkBOB faucet service
====

This service is monitoring withdrawals from zkBOB pool and reward BOB tokens recipients with small amount of gas token.

## Run by docker CLI

1. Prepare `.env` file with the following (at least) variables definitons:

   ```bash
   FAUCET_PRIVKEY=cafe...cafe
   JSON_DB_DIR=/db
   INITIAL_START_BLOCK=123
   ```

   See below with the variables explanation.

2. Create the directory where the faucet service will store its data.

   ```bash
   mkdir ./db
   ```

3. Run the service 

   ```bash
   docker run -ti --rm -v $(pwd)/db:/db --env-file .env ghcr.io/zkBob/zkbob-faucet:latest 
   ```
   
   _Note:_ the source mount point after the key `-v` is the directory created on the step 2. The destination mount point is the directory specified in the variable `JSON_DB_DIR`.

## Run by docker-compose

1. Create the directory where the faucet service will store its data.

   ```bash
   mkdir ./db
   ```

2. Initialize the `docker-compose.yml` file based on `docker-compose.yml.example`. Set proper values for the following variables (at least) there: `FAUCET_PRIVKEY`, `JSON_DB_DIR` and `INITIAL_START_BLOCK`.

   Make sure that the source mount point in the `volumes` section is the directory created on the step 1.

   See below with the variables explanation.

3. Run the service 

   ```bash
   docker-compose up -d
   ```

## Faucet configuration 

The following environment variables may be used to configure the faucet behavior:

1. `ZKBOB_RPC` - JSON RPC endpoint the faucet uses to monitor OB events and get data. **Default:** `https://polygon-rpc.com`.
2. `HISTORY_BLOCK_RANGE` - depends on the RPC endpoints - how deep in the block history transactions logs can be requested. **Default:** `10000`.
3. `BOB_TOKEN` - an address of the BOB token contract. **Default:** `0xB0B195aEFA3650A6908f15CdaC7D92F8a5791B0B`.
4. `POOL_CONTRACT` - an address of the zkBOB pool contract. **Default:** `0xB0B195aEFA3650A6908f15CdaC7D92F8a5791B0B`.
6. `FAUCET_PRIVKEY` - a private key of an account holding xdai to reward. **No default value!**.
7. `GAS_PRICE` - the gas price (in gwei) the faucet uses for reward transactions (pre-EIP1559 transactions). `-1` means to use EIP1559 transactions. **Default:** `-1`.
8. `HISTORICAL_BASE_FEE_DEPTH` - number of recent blocks to estimate the base fee as per gas (EIP1559 related). **Default:** `20`.
10. `BASE_FEE_RATIO` - a coefficient to adjust the base fee per gas acquired from the historical data (EIP1559 related). **Default:** `1.3`.
11. `FEE_LIMIT` - the higher bound of max fee per gas (in gwei) which is used in order to avoid expensive transactions (EIP1559 related). **Default:** `150`.
12. `GAS_LIMIT` - the gas limit the faucet uses for reward transactions. **Default:** `30000`.
13. `REWARD` - amount of xdai used as reward. **Default:** `0.1`.
14. `POLLING_INTERVAL` - amount of time (in seconds) between two subsequent cycles to discover OB transfers and send rewards. **Default:** `60`.
15. `INITIAL_START_BLOCK` - a block the first faucet's attempt to discover OB transfers starts from. **No default value!**.
16. `FINALIZATION_INTERVAL` - a number of blocks starting from the chain head to consider the chain as finalized. **Default:** `128`.
17. `JSON_DB_DIR` - a directory where the faucet service keeps its data. **If not configured, the latest block - HISTORY_BLOCK_RANGE is taken**.
18. `JSON_START_BLOCK` - a name of JSON file where the last observed block is stored. **Default:** `faucet_start_block.json`.
19. `JSON_CONTRACTS` - a name of JSON file where addresses of recipient-contracts are stored. **Default:** `xdai-contracts.json`.
20. `TEST_TO_SEND` - make a transaction to itself just after running the service. **Default:** `false`.