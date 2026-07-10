package com.gitshrl.autox;

import android.accessibilityservice.AccessibilityService;
import android.content.Intent;
import android.util.Log;
import android.view.accessibility.AccessibilityEvent;

/**
 * The device-side half of autox: an AccessibilityService that reads the live UI
 * tree and serves it, uiautomator-free, over a localhost RPC socket.
 *
 * Enabled over adb (no root) — see the repo's ARCHITECTURE.md. Once enabled,
 * Android keeps the service bound, so the RPC port is up for the whole session.
 * The service does no work on events; the client polls {@code /dump} on demand.
 */
public class AutoxAccessibilityService extends AccessibilityService {

    static final String TAG = "autox";
    static final int RPC_PORT = 9008;

    private RpcServer rpc;

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        if (rpc == null) {
            rpc = new RpcServer(this, RPC_PORT);
            rpc.start();
            Log.i(TAG, "RPC server listening on 127.0.0.1:" + RPC_PORT);
        }
    }

    /** No-op: autox polls the tree on demand, it does not react to events. */
    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
    }

    @Override
    public void onInterrupt() {
    }

    @Override
    public boolean onUnbind(Intent intent) {
        if (rpc != null) {
            rpc.stop();
            rpc = null;
        }
        return super.onUnbind(intent);
    }

    /** Current UI hierarchy as uiautomator-compatible XML, or null for a dead tree. */
    String dumpHierarchy() {
        return HierarchyDumper.dump(this);
    }
}
