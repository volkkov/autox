package com.gitshrl.autox;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.content.Intent;
import android.graphics.Path;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;
import android.view.accessibility.AccessibilityEvent;
import android.widget.Toast;

import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

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
                // The first entry is the toast message; later entries are the
                // app label / icon description, so don't concatenate them.
                CharSequence msg = texts.get(0);
                if (msg != null && msg.length() > 0) {
                    lastToast = msg.toString();
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

    /** Dispatch a multi-touch gesture; each stroke is {x1,y1,x2,y2}, all run
     * simultaneously (two strokes make a pinch). Returns whether it completed. */
    boolean dispatchStrokes(int[][] strokes, long durationMs) {
        GestureDescription.Builder builder = new GestureDescription.Builder();
        for (int[] s : strokes) {
            Path path = new Path();
            path.moveTo(s[0], s[1]);
            path.lineTo(s[2], s[3]);
            builder.addStroke(new GestureDescription.StrokeDescription(path, 0, Math.max(durationMs, 1)));
        }
        final boolean[] completed = {false};
        final CountDownLatch latch = new CountDownLatch(1);
        boolean dispatched = dispatchGesture(builder.build(), new GestureResultCallback() {
            @Override
            public void onCompleted(GestureDescription gesture) {
                completed[0] = true;
                latch.countDown();
            }

            @Override
            public void onCancelled(GestureDescription gesture) {
                latch.countDown();
            }
        }, null);
        if (!dispatched) {
            return false;
        }
        try {
            latch.await(durationMs + 1500, TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        return completed[0];
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
