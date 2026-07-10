package com.gitshrl.autox;

import android.accessibilityservice.AccessibilityService;
import android.content.Intent;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;
import android.view.accessibility.AccessibilityEvent;
import android.widget.Toast;

import java.util.List;

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
    // NOT 9008 — that is uiautomator2's jsonrpc port; a leftover u2 server there
    // would block our bind. Must match autox.treesource.DEFAULT_RPC_PORT.
    static final int RPC_PORT = 9998;

    private RpcServer rpc;
    private volatile String lastToast = "";
    private volatile long lastToastAt = 0;

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        if (rpc == null) {
            rpc = new RpcServer(this, RPC_PORT);
            rpc.start();
            Log.i(TAG, "RPC server listening on 127.0.0.1:" + RPC_PORT);
        }
    }

    /** Capture toast text; the client reads the last one via /toast. Toasts
     * arrive as NOTIFICATION_STATE_CHANGED events with no Notification payload. */
    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event.getEventType() == AccessibilityEvent.TYPE_NOTIFICATION_STATE_CHANGED
                && event.getParcelableData() == null) {
            List<CharSequence> texts = event.getText();
            if (texts != null && !texts.isEmpty()) {
                StringBuilder sb = new StringBuilder();
                for (CharSequence t : texts) {
                    if (t != null) {
                        sb.append(t);
                    }
                }
                if (sb.length() > 0) {
                    lastToast = sb.toString();
                    lastToastAt = SystemClock.uptimeMillis();
                }
            }
        }
    }

    String lastToast() {
        return lastToast;
    }

    long lastToastAgeMs() {
        return lastToastAt == 0 ? -1 : SystemClock.uptimeMillis() - lastToastAt;
    }

    void showToast(final String text) {
        new Handler(Looper.getMainLooper()).post(() -> Toast.makeText(this, text, Toast.LENGTH_SHORT).show());
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
