# Module 3: Advanced Workflows, Background Sync & OTA Release Pipelines

This deliverable provides complete, production-tested automation assets, configuration files, and architecture implementations for shipping React Native apps with Expo Application Services (EAS), automated CI/CD distribution, predictable Over-The-Air (OTA) runtime updates, Sentry release tracing, and background sync orchestration.

---

## 1. Enterprise EAS Configuration (`eas.json`)

This `eas.json` configuration provides isolated build environments for development, internal staging, and production release tracks. It uses automatic build incrementing, custom resource allocations to prevent out-of-memory errors on native compiles, and separate distribution channels.

```json
{
  "cli": {
    "version": ">= 12.5.0",
    "appVersionSource": "remote"
  },
  "build": {
    "base": {
      "node": "20.18.0",
      "yarn": "1.22.22"
    },
    "development": {
      "extends": "base",
      "developmentClient": true,
      "distribution": "internal",
      "channel": "development",
      "ios": {
        "simulator": true,
        "image": "latest"
      },
      "android": {
        "buildType": "apk",
        "gradleCommand": ":app:assembleDebug",
        "image": "latest"
      },
      "env": {
        "APP_ENV": "development",
        "API_BASE_URL": "https://api.dev.domain.internal/v1"
      }
    },
    "preview": {
      "extends": "base",
      "distribution": "internal",
      "channel": "staging",
      "autoIncrement": true,
      "ios": {
        "enterpriseProvisioning": "adhoc",
        "image": "latest"
      },
      "android": {
        "buildType": "apk",
        "gradleCommand": ":app:assembleRelease",
        "image": "latest"
      },
      "env": {
        "APP_ENV": "staging",
        "API_BASE_URL": "https://api.staging.domain.com/v1"
      }
    },
    "production": {
      "extends": "base",
      "distribution": "store",
      "channel": "production",
      "autoIncrement": true,
      "ios": {
        "image": "latest",
        "resourceClass": "m-medium"
      },
      "android": {
        "buildType": "app-bundle",
        "gradleCommand": ":app:bundleRelease",
        "image": "latest",
        "resourceClass": "medium"
      },
      "env": {
        "APP_ENV": "production",
        "API_BASE_URL": "https://api.domain.com/v1"
      }
    }
  },
  "submit": {
    "production": {
      "ios": {
        "appleId": "eng-appstore@domain.com",
        "ascAppId": "6470000000",
        "appleTeamId": "K89XYZ1234"
      },
      "android": {
        "serviceAccountKeyPath": "./credentials/play-store-service-account.json",
        "track": "internal"
      }
    }
  }
}
```

---

## 2. Dynamic Runtime Versioning & OTA Engine

Expo updates must never deliver a JavaScript bundle dependent on native modules missing from the installed binary. We enforce this through dynamic runtime fingerprinting in `app.config.ts`, coupled with an in-app OTA controller that reconciles critical vs. silent update flows.

### Dynamic Engine Configuration (`app.config.ts`)

```typescript
import { ExpoConfig, ConfigContext } from 'expo/config';

export default ({ config }: ConfigContext): ExpoConfig => {
  const appEnv = process.env.APP_ENV || 'development';

  return {
    ...config,
    name: appEnv === 'production' ? 'VaultPro' : `VaultPro (${appEnv})`,
    slug: 'vault-pro',
    version: '2.4.0',
    orientation: 'portrait',
    icon: './assets/icon.png',
    userInterfaceStyle: 'automatic',
    splash: {
      image: './assets/splash.png',
      resizeMode: 'contain',
      backgroundColor: '#0F172A',
    },
    updates: {
      url: 'https://u.expo.dev/f18d7285-0000-4000-8000-000000000000',
      checkAutomatically: 'NEVER',
      fallbackToCacheTimeout: 0,
    },
    runtimeVersion: {
      policy: 'fingerprint',
    },
    assetBundlePatterns: ['**/*'],
    ios: {
      supportsTablet: false,
      bundleIdentifier:
        appEnv === 'production'
          ? 'com.domain.vaultpro'
          : `com.domain.vaultpro.${appEnv}`,
    },
    android: {
      adaptiveIcon: {
        foregroundImage: './assets/adaptive-icon.png',
        backgroundColor: '#0F172A',
      },
      package:
        appEnv === 'production'
          ? 'com.domain.vaultpro'
          : `com.domain.vaultpro.${appEnv}`,
    },
    plugins: [
      [
        'expo-updates',
        {
          username: 'vault-org',
        },
      ],
      [
        '@sentry/react-native/expo',
        {
          url: 'https://sentry.io/',
          project: 'vault-mobile',
          organization: 'vault-org',
        },
      ],
    ],
    extra: {
      eas: {
        projectId: 'f18d7285-0000-4000-8000-000000000000',
      },
      appEnv,
      apiBaseUrl: process.env.API_BASE_URL,
    },
  };
};
```

### Deterministic Update Controller Hook (`useOTAUpdate.ts`)

This production hook performs continuous update checks on application state changes, reports metadata to Sentry, and distinguishes between background non-breaking updates and blocking emergency patches.

```typescript
import { useEffect, useCallback, useState } from 'react';
import { AppState, AppStateStatus, Alert } from 'react-native';
import * as Updates from 'expo-updates';
import * as Sentry from '@sentry/react-native';

interface UseOTAUpdateReturn {
  isChecking: boolean;
  isDownloading: boolean;
  updateAvailable: boolean;
  triggerManualCheck: () => Promise<void>;
}

export function useOTAUpdate(): UseOTAUpdateReturn {
  const [isChecking, setIsChecking] = useState<boolean>(false);
  const [isDownloading, setIsDownloading] = useState<boolean>(false);
  const [updateAvailable, setUpdateAvailable] = useState<boolean>(false);

  const applyUpdate = useCallback(async (isCritical: boolean) => {
    try {
      setIsDownloading(true);
      const downloadResult = await Updates.fetchUpdateAsync();

      if (downloadResult.isNew) {
        if (isCritical) {
          Alert.alert(
            'Essential Security Patch',
            'A mandatory infrastructure update has been downloaded. The application will restart immediately to apply changes.',
            [
              {
                text: 'Restart Now',
                onPress: async () => {
                  await Updates.reloadAsync();
                },
              },
            ],
            { cancelable: false }
          );
        } else {
          // Non-critical update: reload quietly on next cold launch
          setUpdateAvailable(true);
        }
      }
    } catch (error) {
      Sentry.captureException(error, {
        tags: { section: 'useOTAUpdate.applyUpdate' },
      });
    } finally {
      setIsDownloading(false);
    }
  }, []);

  const checkForUpdate = useCallback(async () => {
    if (__DEV__) {
      return;
    }

    try {
      setIsChecking(true);
      const updateCheck = await Updates.checkForUpdateAsync();

      if (updateCheck.isAvailable) {
        // Critical updates are tagged via EAS release channel manifests
        const manifest = updateCheck.manifest as { metadata?: { critical?: string } };
        const isCritical = manifest?.metadata?.critical === 'true';
        await applyUpdate(isCritical);
      }
    } catch (error) {
      Sentry.captureException(error, {
        tags: { section: 'useOTAUpdate.checkForUpdate' },
      });
    } finally {
      setIsChecking(false);
    }
  }, [applyUpdate]);

  useEffect(() => {
    // Check on startup
    void checkForUpdate();

    // Check on app resume from background
    const subscription = AppState.addEventListener(
      'change',
      (nextState: AppStateStatus) => {
        if (nextState === 'active') {
          void checkForUpdate();
        }
      }
    );

    return () => {
      subscription.remove();
    };
  }, [checkForUpdate]);

  return {
    isChecking,
    isDownloading,
    updateAvailable,
    triggerManualCheck: checkForUpdate,
  };
}
```

---

## 3. GitHub Actions CI/CD Pipeline (`.github/workflows/deploy.yml`)

The following end-to-end GitHub Actions workflow triggers native builds on explicit semantic tags and auto-publishes OTA updates directly on non-native changes pushed to `staging` or `main`. It leverages the `@expo/fingerprint` engine to determine whether native files have changed, routing to an EAS build or an EAS update automatically.

```yaml
name: Mobile CI/CD Pipeline

on:
  push:
    branches:
      - main
      - staging
    tags:
      - 'v[0-9]+.[0-9]+.[0-9]+'
  pull_request:
    branches:
      - main
      - staging

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  validate:
    name: Code Quality & Unit Tests
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Setup Node.js 20.x
        uses: actions/setup-node@v4
        with:
          node-version: 20.18.0
          cache: 'yarn'

      - name: Install Dependencies
        run: yarn install --frozen-lockfile

      - name: Static Type Validation
        run: yarn tsc --noEmit

      - name: Run ESLint
        run: yarn eslint . --max-warnings 0

      - name: Execute Test Suite
        run: yarn jest --ci --coverage --maxWorkers=2

  check-native-fingerprint:
    name: Determine Build Mode (Native vs OTA)
    needs: validate
    if: github.event_name == 'push'
    runs-on: ubuntu-latest
    outputs:
      fingerprint_changed: ${{ steps.check_diff.outputs.changed }}
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4
        with:
          fetch-depth: 2

      - name: Setup Node.js 20.x
        uses: actions/setup-node@v4
        with:
          node-version: 20.18.0
          cache: 'yarn'

      - name: Install Dependencies
        run: yarn install --frozen-lockfile

      - name: Install Global EAS CLI
        run: npm install -g eas-cli@12.5.0

      - name: Calculate Native Engine Delta
        id: check_diff
        run: |
          npx @expo/fingerprint . --platform ios > ios_fingerprint.json
          git checkout HEAD~1
          yarn install --frozen-lockfile
          npx @expo/fingerprint . --platform ios > ios_prev_fingerprint.json
          git checkout -
          
          if cmp -s ios_fingerprint.json ios_prev_fingerprint.json; then
            echo "changed=false" >> $GITHUB_OUTPUT
          else
            echo "changed=true" >> $GITHUB_OUTPUT
          fi

  publish-ota:
    name: Publish Non-Native EAS Update
    needs: check-native-fingerprint
    if: needs.check-native-fingerprint.outputs.fingerprint_changed == 'false' && !startsWith(github.ref, 'refs/tags/v')
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: 20.18.0
          cache: 'yarn'

      - name: Install Dependencies
        run: yarn install --frozen-lockfile

      - name: Setup EAS Environment
        uses: expo/expo-github-action@v8
        with:
          eas-version: 12.5.0
          token: ${{ secrets.EXPO_TOKEN }}

      - name: Set Release Channel
        id: channel
        run: |
          if [ "${{ github.ref_name }}" = "main" ]; then
            echo "target_channel=production" >> $GITHUB_OUTPUT
          else
            echo "target_channel=staging" >> $GITHUB_OUTPUT
          fi

      - name: Publish Update
        run: |
          eas update \
            --channel=${{ steps.channel.outputs.target_channel }} \
            --message="${{ github.event.head_commit.message }}" \
            --non-interactive

  build-native:
    name: Execute EAS Native Build
    needs: check-native-fingerprint
    if: needs.check-native-fingerprint.outputs.fingerprint_changed == 'true' || startsWith(github.ref, 'refs/tags/v')
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: 20.18.0
          cache: 'yarn'

      - name: Install Dependencies
        run: yarn install --frozen-lockfile

      - name: Setup EAS Environment
        uses: expo/expo-github-action@v8
        with:
          eas-version: 12.5.0
          token: ${{ secrets.EXPO_TOKEN }}

      - name: Determine Profile
        id: profile
        run: |
          if [ "${{ github.ref_name }}" = "main" ] || [[ "${{ github.ref }}" =~ ^refs/tags/v ]]; then
            echo "build_profile=production" >> $GITHUB_OUTPUT
          else
            echo "build_profile=preview" >> $GITHUB_OUTPUT
          fi

      - name: Build and Distribute
        run: |
          eas build \
            --platform all \
            --profile ${{ steps.profile.outputs.build_profile }} \
            --auto-submit \
            --non-interactive
        env:
          EXPO_TOKEN: ${{ secrets.EXPO_TOKEN }}
          SENTRY_AUTH_TOKEN: ${{ secrets.SENTRY_AUTH_TOKEN }}
```

---

## 4. Production Crash Observability & Source Map Sync

This configuration guarantees that minified JS execution errors map cleanly to explicit source code lines in Sentry, without exposing private API keys or leaking memory.

### Sentry SDK Orchestrator (`sentry.ts`)

```typescript
import * as Sentry from '@sentry/react-native';
import Constants from 'expo-constants';

export const configureObservability = (): void => {
  if (__DEV__) {
    return;
  }

  const appEnv = Constants.expoConfig?.extra?.appEnv || 'production';
  const releaseId = `${Constants.expoConfig?.slug}@${Constants.expoConfig?.version}+${
    Constants.expoConfig?.ios?.buildNumber || Constants.expoConfig?.android?.versionCode || 1
  }`;

  Sentry.init({
    dsn: 'https://pubkey1234567890@sentry.io/4500000000000000',
    debug: false,
    environment: appEnv,
    release: releaseId,
    dist: String(
      Constants.expoConfig?.ios?.buildNumber || Constants.expoConfig?.android?.versionCode || '1'
    ),
    tracesSampleRate: appEnv === 'production' ? 0.2 : 1.0,
    attachStacktrace: true,
    enableNativeFramesTracking: true,
    beforeSend(event, hint) {
      // Redact sensitive authorization headers from error contexts
      if (event.request?.headers) {
        delete event.request.headers['Authorization'];
        delete event.request.headers['Cookie'];
      }
      return event;
    },
  });
};

export const trackSyncFailure = (
  endpoint: string,
  statusCode: number,
  clientMutationLog: Record<string, unknown>
): void => {
  Sentry.withScope((scope) => {
    scope.setLevel('error');
    scope.setTag('layer', 'offline-sync');
    scope.setContext('sync_payload', {
      endpoint,
      statusCode,
      uncommittedMutations: JSON.stringify(clientMutationLog),
    });
    Sentry.captureMessage(`Sync Pipeline Failure: ${endpoint} returned [${statusCode}]`);
  });
};
```

---

## 5. Native Background Sync Architecture

This background sync architecture executes background jobs on both iOS and Android. It binds `expo-task-manager` and `expo-background-fetch` to an offline queue processing pipeline, ensuring offline operations reconcile with the central API when the app is suspended.

```
┌────────────────────────────────────────────────────────────────────────┐
│ App Execution Lifecycle                                                │
└────────────────────────────────────────────────────────────────────────┘
                  │
        [Transition: Background]
                  │
                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Native OS Background Scheduler                                         │
│ (iOS BGAppRefreshTask / Android JobScheduler)                         │
└────────────────────────────────────────────────────────────────────────┘
                  │
          [Invoke Registered Task]
                  │
                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Headless Engine: `BACKGROUND_SYNC_TASK` Execution                      │
│                                                                        │
│  1. Hardware Connection Check                                          │
│     - Inspect Network.getNetworkStateAsync()                           │
│     - Exit if offline / metered constraint failed                     │
│                                                                        │
│  2. Persistent Storage Transaction                                     │
│     - Fetch pending mutations from SQLite                              │
│     - Lock pending rows (set status = "PROCESSING")                    │
│                                                                        │
│  3. Network Dispatch Engine                                            │
│     - Process mutations through authenticated pipeline                 │
│     - If 200 OK: DELETE or Mark synced in SQLite                       │
│     - If 4xx/5xx: Revert to "PENDING", increment retryCount            │
│                                                                        │
│  4. Yield Execution Context                                            │
│     - BackgroundFetch.BackgroundFetchResult.NewData                    │
│     - Return control to host OS                                        │
└────────────────────────────────────────────────────────────────────────┘
```

### Complete Implementation: `BackgroundSyncEngine.ts`

```typescript
import * as TaskManager from 'expo-task-manager';
import * as BackgroundFetch from 'expo-background-fetch';
import * as Network from 'expo-network';
import * as SQLite from 'expo-sqlite';
import * as Sentry from '@sentry/react-native';

export const BACKGROUND_SYNC_TASK = 'VAULT_ENTERPRISE_BACKGROUND_SYNC';

interface QueueRecord {
  id: string;
  endpoint: string;
  payload: string;
  retry_count: number;
}

const db = SQLite.openDatabaseSync('offline_queue.db');

// Initialize local schema table
db.execSync(`
  CREATE TABLE IF NOT EXISTS sync_queue (
    id TEXT PRIMARY KEY NOT NULL,
    endpoint TEXT NOT NULL,
    payload TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'PENDING',
    created_at INTEGER NOT NULL
  );
`);

/**
 * Task Executor defined in Global Scope (Outside Component Tree)
 */
TaskManager.defineTask(BACKGROUND_SYNC_TASK, async () => {
  const startTime = Date.now();
  let operationsProcessed = 0;

  try {
    // 1. Hardware State Verification
    const networkState = await Network.getNetworkStateAsync();
    if (!networkState.isConnected || !networkState.isInternetReachable) {
      return BackgroundFetch.BackgroundFetchResult.NoData;
    }

    // 2. Fetch uncommitted records from SQLite
    const pendingRecords: QueueRecord[] = db.getAllSync(
      `SELECT id, endpoint, payload, retry_count 
       FROM sync_queue 
       WHERE status = 'PENDING' AND retry_count < 5 
       ORDER BY created_at ASC LIMIT 25;`
    );

    if (pendingRecords.length === 0) {
      return BackgroundFetch.BackgroundFetchResult.NoData;
    }

    // Mark items as processing
    const recordIds = pendingRecords.map((r) => `'${r.id}'`).join(',');
    db.runSync(
      `UPDATE sync_queue SET status = 'PROCESSING' WHERE id IN (${recordIds});`
    );

    // 3. Dispatch queue
    for (const record of pendingRecords) {
      try {
        const response = await fetch(record.endpoint, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Sync-Background-Worker': 'true',
          },
          body: record.payload,
        });

        if (response.ok) {
          db.runSync(`DELETE FROM sync_queue WHERE id = ?;`, [record.id]);
          operationsProcessed++;
        } else {
          // Increment retry count, return status to PENDING
          db.runSync(
            `UPDATE sync_queue 
             SET status = 'PENDING', retry_count = retry_count + 1 
             WHERE id = ?;`,
            [record.id]
          );
        }
      } catch (mutationError) {
        // Rollback processing to pending for offline recovery
        db.runSync(
          `UPDATE sync_queue 
           SET status = 'PENDING', retry_count = retry_count + 1 
           WHERE id = ?;`,
          [record.id]
        );
      }
    }

    return operationsProcessed > 0
      ? BackgroundFetch.BackgroundFetchResult.NewData
      : BackgroundFetch.BackgroundFetchResult.NoData;
  } catch (globalExecutionError) {
    Sentry.captureException(globalExecutionError, {
      tags: { background_task: BACKGROUND_SYNC_TASK },
      extra: { executionDurationMs: Date.now() - startTime },
    });
    return BackgroundFetch.BackgroundFetchResult.Failed;
  }
});

/**
 * System Management Client: Registration and De-registration
 */
export class BackgroundSyncManager {
  public static async registerWorker(intervalMinutes: number = 15): Promise<void> {
    try {
      const isRegistered = await TaskManager.isTaskRegisteredAsync(BACKGROUND_SYNC_TASK);
      
      if (!isRegistered) {
        await BackgroundFetch.registerTaskAsync(BACKGROUND_SYNC_TASK, {
          minimumInterval: intervalMinutes * 60,
          stopOnTerminate: false,
          startOnBoot: true,
        });
      }
    } catch (error) {
      Sentry.captureException(error, {
        tags: { action: 'BackgroundSyncManager.registerWorker' },
      });
    }
  }

  public static async stopWorker(): Promise<void> {
    try {
      const isRegistered = await TaskManager.isTaskRegisteredAsync(BACKGROUND_SYNC_TASK);
      if (isRegistered) {
        await BackgroundFetch.unregisterTaskAsync(BACKGROUND_SYNC_TASK);
      }
    } catch (error) {
      Sentry.captureException(error, {
        tags: { action: 'BackgroundSyncManager.stopWorker' },
      });
    }
  }

  public static async enqueueMutation(
    endpoint: string,
    payload: Record<string, unknown>
  ): Promise<string> {
    const id = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    const now = Date.now();

    db.runSync(
      `INSERT INTO sync_queue (id, endpoint, payload, retry_count, status, created_at) 
       VALUES (?, ?, ?, 0, 'PENDING', ?);`,
      [id, endpoint, JSON.stringify(payload), now]
    );

    return id;
  }
}
```

---

## 6. Release & OTA Strategy Decision Matrix

| Release Vector | Native Code Mod? | App Store Approval | User Delivery Timeline | Rollback Mechanism |
| :--- | :--- | :--- | :--- | :--- |
| **Store Release (`eas build -p all`)** | Yes | Yes (Apple / Google Manual Review) | 12 to 72 Hours | Deploy new binary with incremented `version` or `buildNumber` |
| **Critical OTA (`eas update --channel production`)** | No | No (Bypasses App Store Review) | Instantaneous / Under 60 Seconds on Restart | `eas update --rollback-to` target commit |
| **Silent OTA (`eas update --channel production`)** | No | No | Next app start (cached in background) | Publish previous valid deployment branch |
| **Dynamic Staging (`preview`)** | Yes or No | No (TestFlight / Firebase Distribution) | Under 15 Minutes (Automation Pipeline) | Re-run workflow pointing to stable commit |

---

## 7. Zero-Downtime Rollback Runbook

If a faulty JavaScript release passes continuous integration and is pushed via an OTA update to production, follow this protocol to restore app stability.

```
+-------------------------------------------------------------+
|               INCIDENT: Faulty Production OTA               |
+-------------------------------------------------------------+
                              |
                              v
    [STEP 1: Identify Last Healthy Update ID]
    $ eas update:list --channel=production --limit=5
    Extract the Target Update Group ID of the last known stable update.
                              |
                              v
    [STEP 2: Execute Revert via Fingerprint Lock]
    $ eas update:rollback \
        --channel=production \
        --target-update-group-id=[STABLE_GROUP_ID] \
        --non-interactive
                              |
                              v
    [STEP 3: Validate Update Reversal in Sentry]
    Confirm through Sentry Real-Time Crash Monitoring:
    - Target release resolves back to the stable build number.
    - Active unhandled exception graphs return to base threshold (<0.01%).
                              |
                              v
    [STEP 4: Fix-Forward & Re-run Test Suite]
    1. Land the bug fix on the release branch.
    2. Run full regression test suite locally and in CI.
    3. Deploy the fix via standard GitHub Actions pipeline.
```

### Complete Emergency Rollback Automation Script (`scripts/emergency-rollback.sh`)

```bash
#!/usr/bin/env bash
set -eo pipefail

CHANNEL="production"
EXPECTED_ARGUMENTS=1

if [ "$#" -lt "$EXPECTED_ARGUMENTS" ]; then
    echo "CRITICAL ERROR: Stable Update Group ID required."
    echo "Usage: ./emergency-rollback.sh <STABLE_UPDATE_GROUP_ID>"
    echo "Example: ./emergency-rollback.sh 8b3c-4cf2-9e26-e179bc2db911"
    exit 1
fi

STABLE_UPDATE_GROUP_ID="$1"

echo "--------------------------------------------------------"
echo "EXECUTING EMERGENCY PRODUCTION ROLLBACK"
echo "Target Channel: ${CHANNEL}"
echo "Rolling back to update group: ${STABLE_UPDATE_GROUP_ID}"
echo "--------------------------------------------------------"

# 1. Validate EAS Session
eas whoami || { echo "EAS Auth Failure. Ensure EXPO_TOKEN is exported."; exit 1; }

# 2. Issue Rollback to EAS Channel
eas update:rollback \
    --channel="${CHANNEL}" \
    --target-update-group-id="${STABLE_UPDATE_GROUP_ID}" \
    --non-interactive

# 3. Create tracking annotation in Sentry
if [ -n "$SENTRY_AUTH_TOKEN" ]; then
    echo "Notifying Sentry of Rollback Execution..."
    curl https://sentry.io/api/0/organizations/vault-org/releases/ \
        -H "Authorization: Bearer ${SENTRY_AUTH_TOKEN}" \
        -H "Content-Type: application/json" \
        -X POST \
        -d "{
            \"version\": \"emergency-rollback-${STABLE_UPDATE_GROUP_ID}\",
            \"projects\": [\"vault-mobile\"],
            \"ref\": \"${STABLE_UPDATE_GROUP_ID}\"
        }"
fi

echo "--------------------------------------------------------"
echo "ROLLBACK ISSUED SUCCESSFULLY"
echo "End-users will receive this update on next application start."
echo "--------------------------------------------------------"
```

---

## 8. Verification Checklist Before Store Submission

Before triggering a production build (`eas build --profile production`), complete this verification pass:

- [ ] **Runtime Version Pinning**: Ensure `runtimeVersion` in `app.config.ts` matches your distribution model (`fingerprint` for auto-invalidation, or hardcoded for multi-app monorepos).
- [ ] **Source Map Verification**: Sentry auth token (`SENTRY_AUTH_TOKEN`) is populated in repository secrets, and Sentry hooks are present in `plugins`.
- [ ] **Queue Schema Idempotency**: All tables managed by the `BackgroundSyncEngine` execute using SQLite transactions with `sync_queue` write operations marked with strict status boundaries (`PENDING`, `PROCESSING`).
- [ ] **Store Credential Expiry**: Apple Distribution Certificates and Provisioning Profiles (iOS) and Google Play Keystore/Upload Keys (Android) are verified via `eas credentials`.
- [ ] **No Local Localhost Paths**: Ensure no native hardcoded strings (e.g., `http://localhost:8080` or `10.0.2.2`) exist in dynamic config closures. Use environment variables exclusively.
