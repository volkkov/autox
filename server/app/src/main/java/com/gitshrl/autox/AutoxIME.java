package com.gitshrl.autox;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.inputmethodservice.InputMethodService;
import android.os.Build;
import android.util.Base64;
import android.view.KeyEvent;
import android.view.View;
import android.view.inputmethod.InputConnection;

import java.nio.charset.StandardCharsets;

/**
 * autox's own text-input IME — a reimplementation of ADBKeyboard bundled in the
 * autox APK, so typing needs no external app.
 *
 * A broadcast receiver (registered while the IME is bound) commits text to the
 * focused field's {@link InputConnection}. The client selects this IME, then
 * broadcasts:
 *   ADB_INPUT_B64  --es msg &lt;base64 utf-8&gt;   commit UTF-8 text (emoji/unicode)
 *   ADB_INPUT_TEXT --es msg &lt;text&gt;           commit plain text
 *   ADB_CLEAR_TEXT                             clear the field
 *   ADB_INPUT_CODE --ei code &lt;keycode&gt;       inject a key event
 *   ADB_EDITOR_CODE --ei code &lt;action&gt;       perform an editor action (search/go/…)
 *
 * The action names match ADBKeyboard's so the client protocol is unchanged; only
 * the active IME differs. No visible keyboard is drawn (a 1px input view keeps
 * the IME "shown" so the client can confirm it is ready).
 */
public class AutoxIME extends InputMethodService {

    private BroadcastReceiver receiver;

    @Override
    public void onCreate() {
        super.onCreate();
        IntentFilter filter = new IntentFilter();
        filter.addAction("ADB_INPUT_TEXT");
        filter.addAction("ADB_INPUT_B64");
        filter.addAction("ADB_CLEAR_TEXT");
        filter.addAction("ADB_INPUT_CODE");
        filter.addAction("ADB_EDITOR_CODE");
        receiver = new BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                handle(intent);
            }
        };
        // The broadcasts come from `am broadcast` (shell), so the receiver must
        // be exported; the explicit flag is required on Android 13+.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(receiver, filter, Context.RECEIVER_EXPORTED);
        } else {
            registerReceiver(receiver, filter);
        }
    }

    @Override
    public void onDestroy() {
        if (receiver != null) {
            unregisterReceiver(receiver);
            receiver = null;
        }
        super.onDestroy();
    }

    /** A 1px view so the IME counts as shown (mInputShown=true) without UI. */
    @Override
    public View onCreateInputView() {
        View v = new View(this);
        v.setMinimumHeight(1);
        return v;
    }

    @Override
    public boolean onEvaluateInputViewShown() {
        return true;
    }

    @Override
    public boolean onEvaluateFullscreenMode() {
        return false;
    }

    private void handle(Intent intent) {
        InputConnection ic = getCurrentInputConnection();
        if (ic == null) {
            return;
        }
        String action = intent.getAction();
        if (action == null) {
            return;
        }
        switch (action) {
            case "ADB_INPUT_B64": {
                String data = intent.getStringExtra("msg");
                if (data != null) {
                    byte[] bytes = Base64.decode(data, Base64.DEFAULT);
                    ic.commitText(new String(bytes, StandardCharsets.UTF_8), 1);
                }
                break;
            }
            case "ADB_INPUT_TEXT": {
                String text = intent.getStringExtra("msg");
                if (text != null) {
                    ic.commitText(text, 1);
                }
                break;
            }
            case "ADB_CLEAR_TEXT": {
                ic.beginBatchEdit();
                ic.performContextMenuAction(android.R.id.selectAll);
                ic.commitText("", 1);
                ic.endBatchEdit();
                break;
            }
            case "ADB_INPUT_CODE": {
                int code = intent.getIntExtra("code", -1);
                if (code >= 0) {
                    ic.sendKeyEvent(new KeyEvent(KeyEvent.ACTION_DOWN, code));
                    ic.sendKeyEvent(new KeyEvent(KeyEvent.ACTION_UP, code));
                }
                break;
            }
            case "ADB_EDITOR_CODE": {
                int code = intent.getIntExtra("code", -1);
                if (code >= 0) {
                    ic.performEditorAction(code);
                }
                break;
            }
            default:
                break;
        }
    }
}
