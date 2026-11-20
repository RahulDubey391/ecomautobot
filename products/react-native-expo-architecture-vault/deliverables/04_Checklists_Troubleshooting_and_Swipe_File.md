# Module 4: App Store Rejection Checklist, Performance Rubrics & Native Swipe File

---

## 1. Zero-Rejection App Store & Google Play Compliance Audit

Submitting a React Native / Expo application to the Apple App Store and Google Play Console requires navigating strict platform constraints. The checklist below targets the root causes of over 95% of native binary and metadata rejections.

### 1.1 Dual-Platform Compliance Matrix

| Audit Target | Apple App Store Guideline | Google Play Policy | React Native / Expo Failure Point | Mandatory Resolution Architecture |
| :--- | :--- | :--- | :--- | :--- |
| **Account Deletion** | **Guideline 5.1.1(v)**: Must initiate account deletion within the app; must delete all data, not just deactivate. | **Data Deletion Policy**: Must provide in-app path *and* external web deletion URL in Data Safety. | Hiding delete behind an email link or webview; failing to revoke Apple Sign-In tokens upon deletion. | Implement native modal calling backend deletion endpoint; revoke Apple tokens via `https://appleid.apple.com/auth/revoke`; expose public URL `https://api.domain.com/user/delete-account`. |
| **IAP vs. External Pay** | **Guideline 3.1.1**: Digital goods/features unlocked via code must use StoreKit. | **Payments Policy**: Digital content consumed in-app must use Google Play Billing. | Linking to Stripe/web checkout for SaaS tier upgrades inside the mobile binary; mentioning "web pricing". | Enforce RevenueCat / native IAP abstraction. Dynamically hide all web checkout links, pricing tables, or "upgrade on web" text when `Platform.OS !== 'web'`. |
| **Data Privacy & Disclosures** | **Guideline 5.1.2**: App Tracking Transparency (ATT) prompt required before collecting IDFA. | **User Data / Data Safety**: Exact disclosure of all collected data types, storage, and sharing. | Initializing analytics (Mixpanel, PostHog, Adjust, AppsFlyer) *before* ATT prompt resolves on iOS; mismatches in Play Data Safety form. | Gate SDK initializations behind an explicit consent state machine. Configure `EXUpdates` and tracking wrappers to wait for `requestTrackingPermissionsAsync()`. |
| **Login Gates & Broken Flow**| **Guideline 2.1**: App completeness. Apps cannot present a blank screen or block all features behind a hard wall without demo creds. | **Broken Functionality**: App must provide core utility without fatal crashes or mandatory unfillable forms. | Reviewer enters sandbox credentials, fails due to backend IP allowlist or missing demo data; reviewer tests on IPv6 and network calls fail. | Provide tested demo credentials in App Store Connect / Play Console notes. Run full IPv6 test runner (`nat64` network simulation). Pre-seed backend test accounts. |
| **Background Permissions** | **Guideline 2.5.4**: Multitasking and background processing must be justified. | **Permissions Policy**: High-risk permissions (Location in Background, Foreground Services) audited strictly. | Including background location flags in `app.json` without active geo-fencing or turn-by-turn navigation; using legacy Foreground Services on Android 14. | Strip unused background permissions (`locationAlwaysAndWhenInUsePermission`). Configure Android 14+ `foregroundServiceType` in `AndroidManifest.xml` via config plugins. |

---

### 1.2 Expo Configuration Enforcement (`app.config.ts`)

Hardening the Expo configuration file against automated submission scanners:

```typescript
// app.config.ts
import { ExpoConfig, ConfigContext } from 'expo/config';

export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: "VaultMobile",
  slug: "vault-mobile",
  version: "1.4.0",
  orientation: "portrait",
  icon: "./assets/icon.png",
  userInterfaceStyle: "automatic",
  splash: {
    image: "./assets/splash.png",
    resizeMode: "contain",
    backgroundColor: "#0F172A",
  },
  ios: {
    supportsTablet: false,
    bundleIdentifier: "com.vault.production",
    buildNumber: "140",
    infoPlist: {
      CFBundleAllowMixedLocalizations: true,
      ITSAppUsesNonExemptEncryption: false,
      NSCameraUsageDescription:
        "VaultMobile uses the camera to scan physical QR codes for zero-knowledge device pairing.",
      NSPhotoLibraryUsageDescription:
        "VaultMobile accesses your photo library exclusively to allow profile avatar selection.",
      NSPhotoLibraryAddUsageDescription:
        "VaultMobile saves generated transaction receipts directly to your photo library upon user request.",
      NSUserTrackingUsageDescription:
        "This identifier will be used to deliver personalized product analytics and prevent fraudulent transactions.",
    },
    entitlements: {
      "aps-environment": "production",
    },
  },
  android: {
    adaptiveIcon: {
      foregroundImage: "./assets/adaptive-icon.png",
      backgroundColor: "#0F172A",
    },
    package: "com.vault.production",
    versionCode: 140,
    compileSdkVersion: 34,
    targetSdkVersion: 34,
    minSdkVersion: 24,
    permissions: [
      "CAMERA",
      "RECEIVE_BOOT_COMPLETED",
      "VIBRATE"
      // Explicitly NO ACCESS_BACKGROUND_LOCATION without justification
    ],
  },
  plugins: [
    [
      "expo-camera",
      {
        cameraPermission: "VaultMobile uses the camera to scan physical QR codes for zero-knowledge device pairing."
      }
    ],
    [
      "expo-image-picker",
      {
        photosPermission: "VaultMobile accesses your photo library exclusively to allow profile avatar selection."
      }
    ],
    [
      "expo-tracking-transparency",
      {
        userTrackingPermission: "This identifier will be used to deliver personalized product analytics and prevent fraudulent transactions."
      }
    ],
    [
      "expo-build-properties",
      {
        android: {
          enableProguardInReleaseBuilds: true,
          enableShrinkResourcesInReleaseBuilds: true,
          extraProguardRules: `
            -keep public class com.horcrux.svg.** { *; }
            -keep class com.facebook.react.turbomodule.** { *; }
          `
        },
        ios: {
          useFrameworks: "static"
        }
      }
    ]
  ],
  extra: {
    eas: {
      projectId: "your-eas-project-id"
    }
  }
});
```

---

## 2. 60fps Gesture & Thread Optimization Cheatsheet

Maintaining a consistent 60fps (or 120fps on ProMotion displays) requires executing all gesture animations on the UI thread using JSI (JavaScript Interface), bypassing the React Native asynchronous bridge entirely.

### 2.1 Rendering Performance Matrix

```
+-------------------------------------------------------------------------------+
| Thread Architecture Performance Map                                          |
+-------------------------------------------------------------------------------+
| [ JavaScript Thread ]             | [ Native / UI Thread ]                    |
| - Business Logic                  | - Gesture Handler v2 Context Engine       |
| - Offline Sync Queues (Watermelon)| - Reanimated 3 Worklet Calculations       |
| - React Reconciliation / Fiber    | - Core Animation / Render Node Pipeline   |
|                                   |                                           |
|       === STALL DETECTED ===      |       === 120 FPS FLUID MOTION ===        |
| JS FPS drops to 0 during sync     | UI FPS stays at 120 without dropping      |
| if worklet offloading is missing  | frames when gesture code is isolated      |
+-------------------------------------------------------------------------------+
```

### 2.2 Reanimated 3 & Gesture Handler 2 Swipable Card Engine

Below is a production-grade, zero-bridge swipe-to-dismiss gesture component. It isolates state transformations completely to the UI thread using JSI worklets.

```tsx
import React from 'react';
import { StyleSheet, View, Text, Dimensions } from 'react-native';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withSpring,
  withTiming,
  runOnJS,
} from 'react-native-reanimated';
import * as Haptics from 'expo-haptics';

const { width: SCREEN_WIDTH } = Dimensions.get('window');
const TRANSLATE_X_THRESHOLD = -SCREEN_WIDTH * 0.3;

interface DismissibleItemProps {
  id: string;
  title: string;
  subtitle: string;
  onDismiss: (id: string) => void;
}

export const DismissibleItem: React.FC<DismissibleItemProps> = ({
  id,
  title,
  subtitle,
  onDismiss,
}) => {
  const translateX = useSharedValue(0);
  const itemHeight = useSharedValue(70);
  const opacity = useSharedValue(1);

  const triggerHaptic = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
  };

  const panGesture = Gesture.Pan()
    .activeOffsetX([-10, 10])
    .onUpdate((event) => {
      // Constrain dragging leftward only
      if (event.translationX < 0) {
        translateX.value = event.translationX;
      }
    })
    .onEnd(() => {
      const shouldDismiss = translateX.value < TRANSLATE_X_THRESHOLD;

      if (shouldDismiss) {
        runOnJS(triggerHaptic)();
        translateX.value = withTiming(-SCREEN_WIDTH, { duration: 200 });
        itemHeight.value = withTiming(0, { duration: 200 });
        opacity.value = withTiming(0, { duration: 200 }, (isFinished) => {
          if (isFinished) {
            runOnJS(onDismiss)(id);
          }
        });
      } else {
        translateX.value = withSpring(0, { damping: 20, stiffness: 200 });
      }
    });

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: translateX.value }],
  }));

  const containerStyle = useAnimatedStyle(() => ({
    height: itemHeight.value,
    opacity: opacity.value,
  }));

  return (
    <Animated.View style={[styles.container, containerStyle]}>
      <View style={styles.deleteBackground}>
        <Text style={styles.deleteText}>Delete</Text>
      </View>
      <GestureDetector gesture={panGesture}>
        <Animated.View style={[styles.card, animatedStyle]}>
          <Text style={styles.title}>{title}</Text>
          <Text style={styles.subtitle}>{subtitle}</Text>
        </Animated.View>
      </GestureDetector>
    </Animated.View>
  );
};

const styles = StyleSheet.create({
  container: {
    width: '100%',
    marginVertical: 4,
    overflow: 'hidden',
    backgroundColor: '#EF4444',
  },
  deleteBackground: {
    ...StyleSheet.absoluteFillObject,
    justifyContent: 'center',
    alignItems: 'flex-end',
    paddingRight: 24,
    backgroundColor: '#EF4444',
  },
  deleteText: {
    color: '#FFFFFF',
    fontWeight: '700',
    fontSize: 14,
    textTransform: 'uppercase',
  },
  card: {
    width: '100%',
    height: 70,
    backgroundColor: '#1E293B',
    paddingHorizontal: 16,
    justifyContent: 'center',
  },
  title: {
    color: '#F8FAFC',
    fontSize: 16,
    fontWeight: '600',
  },
  subtitle: {
    color: '#94A3B8',
    fontSize: 12,
    marginTop: 2,
  },
});
```

### 2.3 FlashList Recycler Engine Rules

When replacing `FlatList` with `@shopify/flash-list`, standard React Native layout rules change. Violating recycling invariants causes blank spaces and dropped frames.

```tsx
import React, { useCallback } from 'react';
import { View, StyleSheet } from 'react-native';
import { FlashList } from '@shopify/flash-list';
import { Image } from 'expo-image';

interface FeedItem {
  id: string;
  imageUrl: string;
  aspectRatio: number;
}

export const OptimizedList: React.FC<{ items: FeedItem[] }> = ({ items }) => {
  // CRITICAL RULE 1: Never instantiate inline functions or objects in renderItem
  const renderItem = useCallback(({ item }: { item: FeedItem }) => {
    return (
      <View style={styles.itemWrapper}>
        <Image
          source={{ uri: item.imageUrl }}
          style={[styles.image, { aspectRatio: item.aspectRatio }]}
          contentFit="cover"
          // CRITICAL RULE 2: Use transition for smooth paint, avoid memory-heavy crossfade
          transition={150}
          cachePolicy="memory-disk"
          // CRITICAL RULE 3: Downsample image to exact container size on native side
          recyclingKey={item.id}
        />
      </View>
    );
  }, []);

  // CRITICAL RULE 4: Explicit KeyExtractor pointing strictly to immutable strings
  const keyExtractor = useCallback((item: FeedItem) => item.id, []);

  return (
    <FlashList
      data={items}
      renderItem={renderItem}
      keyExtractor={keyExtractor}
      // CRITICAL RULE 5: Exact estimatedItemSize calculated from median height
      estimatedItemSize={240}
      // CRITICAL RULE 6: Set overrideItemLayout if layout sizes are deterministic
      drawDistance={300}
      showsVerticalScrollIndicator={false}
    />
  );
};

const styles = StyleSheet.create({
  itemWrapper: {
    width: '100%',
    paddingHorizontal: 16,
    paddingVertical: 8,
    backgroundColor: '#0F172A',
  },
  image: {
    width: '100%',
    borderRadius: 8,
    backgroundColor: '#1E293B',
  },
});
```

---

## 3. Memory Leak & Bridge Saturation Diagnostics Manual

Memory leaks in React Native apps with offline sync layers typically stem from three vectors: un-garbage-collected native event emitters, dangling JSI references (SQLite/WatermelonDB iterators), and unbound global subscriptions.

### 3.1 Systematic Leak Hunting with Xcode & Android Profiler

#### Step 1: Native Boundary Verification (Xcode Instruments)
1. Build the production variant locally: `npx expo run:ios --configuration Release`.
2. Open Xcode, select **Product > Profile** (`Cmd + I`).
3. Select the **Leaks** template.
4. Filter by the process `VaultMobile`. Focus exclusively on the **Allocations** instrument.
5. Search for `HermesRuntime`, `RCTEventEmitter`, and native image layers (`CGImage`, `UIImage`).
6. Repeatedly push and pop the heaviest screen (e.g., sync list with charts) 20 times.
7. If **Persistent Bytes** climbs monotonically without flattening out after a GC sweep, inspect the **Call Tree** with *Invert Call Tree* and *Hide System Libraries* checked. Look for retained `std::function` or native callback blocks.

#### Step 2: Native Android Bitmap Auditing (Android Studio Profiler)
1. Run `npx expo run:android --variant release`.
2. Attach the **Android Profiler** to `com.vault.production`.
3. Force garbage collection using the trash can icon.
4. Record a **Java/Kotlin Allocations** heap dump.
5. Sort classes by count of `Bitmap` and `NativeAllocationRegistry`.
6. Inspect instances: if bitmaps are retained after navigating away, an image package or cache layer is failing to invoke `.recycle()` or release native JNI handles.

---

### 3.2 Automated Subscription & Listener Leak-Detection Hook

Use this defensive hook to audit any custom native event listener, WebSocket pipeline, or offline database observer. It alerts developers in `__DEV__` mode when an unmounted component leaves an active reference alive past the defined threshold.

```typescript
import { useEffect, useRef } from 'react';

interface SubscriptionTarget {
  remove?: () => void;
  unsubscribe?: () => void;
}

export function useLeakSafeSubscription<T extends SubscriptionTarget>(
  subscriptionFactory: () => T,
  identifier: string
): void {
  const isCleanedUp = useRef<boolean>(false);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    isCleanedUp.current = false;
    const subscription = subscriptionFactory();

    return () => {
      isCleanedUp.current = true;
      
      // Execute teardown
      if (typeof subscription.remove === 'function') {
        subscription.remove();
      } else if (typeof subscription.unsubscribe === 'function') {
        subscription.unsubscribe();
      } else {
        console.warn(
          `[Memory Management] Subscribed target "${identifier}" lacks an unsubscribe/remove interface.`
        );
      }

      // Canary assertion: verify no retained asynchronous work runs post-unmount
      if (__DEV__) {
        timerRef.current = setTimeout(() => {
          if (!isCleanedUp.current) {
            console.error(
              `[LEAK DETECTED] Retained subscription reference detected in "${identifier}" post-unmount.`
            );
          }
        }, 5000);
      }
    };
  }, [subscriptionFactory, identifier]);
}
```

---

### 3.3 Bridge Saturation Diagnostics Matrix

```typescript
// Monitoring Bridge/JSI Event Throughput in Dev Environments
let callCounter = 0;
let lastReset = Date.now();

export const trackInteractionThroughput = (metricTag: string) => {
  if (!__DEV__) return;
  
  callCounter++;
  const now = Date.now();
  
  if (now - lastReset > 1000) {
    if (callCounter > 60) {
      console.warn(
        `[BRIDGE CONGESTION ALERT] "${metricTag}" executed ${callCounter} bridge/JSI invocations in 1000ms. UI thread drop likely.`
      );
    }
    callCounter = 0;
    lastReset = now;
  }
};
```

---

## 4. Production Swipe File: Rejection Appeal Templates & Blueprints

The following appeal letters are field-tested templates extracted from real enterprise releases. Use them as base blueprints when handling rejections, replacing only the specific architectural details while retaining the formal structure and guideline references.

---

### Appeal Blueprint 1: Apple Guideline 3.1.1 (Business Model / Digital vs. Physical / Enterprise Exemption)

*Context:* Apple rejects the app alleging that digital memberships, enterprise multi-seat licenses, or off-app invoices bypass StoreKit.

```text
To the Apple App Store Review Board,

Subject: Formal Appeal Regarding Guideline 3.1.1 (Payments - In-App Purchase) for App ID: com.vault.production

We are writing to respectfully appeal the rejection issued under Guideline 3.1.1 regarding the monetization architecture of VaultMobile (Version 1.4.0).

1. Architectural Clarification:
The reviewer noted that our application allows corporate administrative users to configure deployment credentials and team roles, inferring that these services constitute unmediated digital goods that must be purchased through In-App Purchase (IAP). 

VaultMobile operates under the Multiplatform Services / Enterprise Management rule outlined in Guideline 3.1.3(c) and Guideline 3.1.3(a). Specifically:
- VaultMobile is a companion client for existing multi-seat Enterprise SaaS contracts negotiated and transacted outside the application via B2B agreements (Master Services Agreements).
- No digital functionality is sold, transacted, or purchased inside the iOS binary. 
- The binary does not contain any links, redirects, WebViews, or language leading consumers to a web-based checkout funnel or external payment gateway. We strictly adhere to Guideline 3.1.1 by ensuring no mechanism within the app promotes an alternative payment path.

2. Codebase Implementation Audit:
We have confirmed that:
a) All API endpoints consumed by this build reject arbitrary client-side payment tokens.
b) The application UI is entirely inert regarding purchasing; it functions exclusively as an authentication terminal via SAML/SSO and an operational dashboard for existing enterprise accounts.
c) There are no references to external pricing, subscription costs, or purchasing guidance within our application copy.

3. Reproduction Steps for App Review:
We have provided an enterprise sandbox account configured without an active seat, illustrating that the user is informed to contact their corporate organization administrator, without any sales links or checkout triggers:
- Username: app-review-enterprise@vault.production
- Password: [SECURE_REVIEW_PASSWORD_HERE]

We respectfully request that the board overturn this rejection and approve Version 1.4.0 for standard distribution under Guideline 3.1.3(c).

Warm regards,

Head of Engineering & Mobile Architecture
VaultMobile Team
```

---

### Appeal Blueprint 2: Apple Guideline 2.1 (Performance - App Completeness & IPv6 Network Failure)

*Context:* App Review reports that the app hangs on launch or cannot establish connectivity on their simulated NAT64/IPv6-only networks.

```text
To the Apple App Store Review Board,

Subject: Technical Documentation & Resolution: Guideline 2.1 (Performance - Launch Stability on IPv6) for App ID: com.vault.production

We have reviewed the rejection feedback indicating that Version 1.4.0 failed to establish an active session during launch in an isolated IPv6 test environment.

1. Root Cause Identification:
Our network diagnostics team replicated the failure using Apple’s official NAT64 network blueprint (macOS Internet Sharing over NAT64/DNS64). The crash/stall occurred because our legacy edge network fallback client performed strict IPv4-literal serialization (`http://192.0.2.1`) during DNS resolution timeouts, bypassing RFC 6052 compliance.

2. Technical Remediation (Resolved in Build 141):
We have modified our mobile networking layer and deployed the following fixes directly to Build 141:
- Replaced custom socket fallback resolutions with native POSIX-compliant hostname lookups via iOS `CFNetwork` APIs, mapped through React Native’s `NSURLSessionConfiguration` engine.
- Ensured zero raw IPv4 address literals exist within our production bundle via AST linting on our CI/CD compilation pipeline.
- Verified that all edge endpoints (`https://api.vault.production/v1`) resolve seamlessly under standard dual-stack and pure IPv6-only environments using `getaddrinfo()` standard primitives.

3. Step-by-Step Verification Path:
We have verified Build 141 against the following conditions:
- Device: iPhone 15 Pro, iOS 17.4
- Network Profile: Isolated Wi-Fi NAT64 Network (OS X DNS64 Prefix: 64:ff9b::/96)
- Result: Cold launch to initial interactive dashboard completes in 1.18 seconds.

Credentials for automated verification remain:
- Review Account: app-review-auditor@vault.production
- Password: [SECURE_REVIEW_PASSWORD_HERE]
- Verification PIN (if 2FA triggers): 849201

We have resubmitted Build 141 and request expedited processing to complete the evaluation.

Sincerely,

Technical Lead, Infrastructure
VaultMobile Team
```

---

### Appeal Blueprint 3: Apple Guideline 5.1.1(v) (Account Deletion Implementation)

*Context:* Apple rejects the app stating that account deletion is either not discoverable, requires external email confirmation, or fails to execute natively.

```text
To the Apple App Store Review Board,

Subject: Verification of Complete Native Account Deletion: Guideline 5.1.1(v) for App ID: com.vault.production

We are writing in response to the Guideline 5.1.1(v) notice regarding our account deletion workflow. We have updated both the in-app experience and our backend compliance pipeline in Build 142.

1. Native Deletion Pipeline Architecture:
The account deletion mechanism inside VaultMobile is entirely native, instantaneous, and fully accessible within two taps from the primary settings hub:
- Path: Settings Tab -> Security & Identity -> Permanently Delete Account.
- Confirmation: The user is presented with a native destructive modal prompt detailing that all cryptographic keys, personal identifier records, and transaction receipts are permanently purged from our databases.
- Execution: Upon confirmation, the app fires a `DELETE /api/v1/user/account` request. If Apple Sign-In was used, our authorization engine immediately invokes the Apple Revoke Token API (`https://appleid.apple.com/auth/revoke`) using our client credentials, severing the authorization relationship at the OS level.
- Local Storage: SQLite local databases, SecureStore tokens, and cached assets are cleared immediately via our zero-fill cleanup service before the user is routed to the unauthenticated onboarding landing screen.

2. Reproduction Steps:
To test the end-to-end deletion lifecycle:
1. Launch Build 142 and log in with:
   - User: review-delete-test@vault.production
   - Pass: [SECURE_REVIEW_PASSWORD_HERE]
2. Tap the bottom right "Settings" tab.
3. Scroll to the "Account Operations" card and tap "Delete Account".
4. Type "DELETE" into the validation alert to confirm intent.
5. The account record will be deleted from our production datastore within 200ms, and the app will reset to the welcome interface.
6. Attempting to log back in with these credentials will immediately return an `HTTP 401: Account Purged` error.

We have attached an MP4 screen recording (`deletion_workflow_verification.mp4`) detailing this exact execution. We look forward to your approval of Build 142.

Regards,

VP of Mobile Engineering
VaultMobile Team
```

---

### Appeal Blueprint 4: Google Play Data Safety & High-Risk Permission Disallowance

*Context:* Google Play rejects the app build due to an unapproved `FOREGROUND_SERVICE` or background location permission usage, or mismatches in the Data Safety form.

```text
To the Google Play Policy Review Team,

Subject: Declaration of Conformance: Android 14 Foreground Service Policies & Data Safety Form for Package: com.vault.production

We are writing to provide detailed technical clarification regarding the rejection of our latest App Bundle (Version Code 140) concerning Android 14 `FOREGROUND_SERVICE` compliance and Data Safety declarations.

1. Remediation of Foreground Service Declarations:
In compliance with Google Play’s Foreground Service permissions policy (Target SDK 34), we have audited our `AndroidManifest.xml` and stripped all generic background worker declarations. 

Our application performs reliable data synchronization for cryptographic cold-storage records. In Version Code 141:
- We have completely removed `android.permission.FOREGROUND_SERVICE_DATA_SYNC`.
- We have transitioned all persistent background synchronization routines to Google’s recommended `androidx.work.WorkManager` framework, running strictly under system-managed opportunistic execution windows via `PeriodicWorkRequestBuilder` with network constraints (`NetworkType.CONNECTED`).
- No long-running background service remains within our native compilation output, which can be verified by decompiling the `.aab` manifest.

2. Data Safety Form Reconciliation:
The automated scanner flagged a discrepancy regarding the collection of "Approximate Location":
- Our application uses `ACCESS_COARSE_LOCATION` exclusively to identify regulatory zones for digital ledger compliance.
- The Data Safety profile has been updated to explicitly reflect that Approximate Location is:
  1. Collected only when the user is actively interacting with the application.
  2. Not shared with third parties.
  3. Encrypted in transit using TLS 1.3.
  4. Ephemeral: purged from edge caches within 15 minutes of session termination.
  5. Completely optional: users can revoke the permission through Android System Settings without breaking unrelated functionality.

3. Artifact Verification:
We have uploaded Version Code 141 directly to the Internal Testing track for immediate validation. We request that the policy violation flag be cleared and the bundle be permitted to proceed to Production.

Respectfully submitted,

Lead Android Architect
VaultMobile Team
```

---

## 5. Pre-Flight Release Command Checklist

Execute this deterministic validation matrix in your terminal prior to every production release tagging:

```bash
#!/usr/bin/env bash
set -eo pipefail

echo "== [Step 1/5] Running Strict TypeScript Compile =="
npx tsc --noEmit

echo "== [Step 2/5] Linting Codebase for Production Rules =="
npx eslint . --max-warnings 0

echo "== [Step 3/5] Auditing app.json / app.config.ts for Missing Permission Strings =="
node -e '
  const config = require("./app.config.ts").default({ config: {} });
  const infoPlist = config.ios.infoPlist;
  const requiredKeys = [
    "NSCameraUsageDescription",
    "NSPhotoLibraryUsageDescription",
    "NSUserTrackingUsageDescription"
  ];
  for (const key of requiredKeys) {
    if (!infoPlist[key] || infoPlist[key].length < 15) {
      console.error(`FATAL: iOS Info.plist missing valid description for ${key}`);
      process.exit(1);
    }
  }
  console.log("iOS Info.plist descriptions verified.");
'

echo "== [Step 4/5] Executing Jest Unit & Performance Regression Suite =="
npm test -- --coverage --silent

echo "== [Step 5/5] Checking Expo Production Config Plugin Merge Output =="
npx expo config --type prebuild > /dev/null

echo ">> PRE-FLIGHT AUDIT PASSED: Ready for EAS Build & Store Dispatch <<"
