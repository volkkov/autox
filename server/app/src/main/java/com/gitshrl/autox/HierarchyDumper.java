package com.gitshrl.autox;

import android.content.Context;
import android.graphics.Rect;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;

import java.util.List;

/**
 * Walks the accessibility tree and serialises it in uiautomator's XML schema —
 * {@code <hierarchy rotation="R">} of {@code <node …/>} carrying
 * bounds/text/resource-id/class/clickable/… — so autox's existing Python parser
 * and selectors consume it unchanged. Bounds are absolute screen pixels
 * ({@link AccessibilityNodeInfo#getBoundsInScreen}), exactly as uiautomator
 * reports them.
 */
final class HierarchyDumper {

    private static final int MAX_DEPTH = 500;

    private HierarchyDumper() {
    }

    /** Returns the hierarchy XML, or null when no window/root is available. */
    static String dump(AutoxAccessibilityService svc) {
        StringBuilder sb = new StringBuilder(64 * 1024);
        sb.append("<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>");
        sb.append("<hierarchy rotation=\"").append(rotation(svc)).append("\">");

        boolean any = false;
        List<AccessibilityWindowInfo> windows = null;
        try {
            windows = svc.getWindows();
        } catch (Exception ignored) {
        }
        if (windows != null && !windows.isEmpty()) {
            int index = 0;
            for (AccessibilityWindowInfo window : windows) {
                AccessibilityNodeInfo root = null;
                try {
                    root = window.getRoot();
                } catch (Exception ignored) {
                }
                if (root != null) {
                    dumpNode(root, sb, index++, 0);
                    any = true;
                }
            }
        }
        if (!any) {
            AccessibilityNodeInfo root = null;
            try {
                root = svc.getRootInActiveWindow();
            } catch (Exception ignored) {
            }
            if (root != null) {
                dumpNode(root, sb, 0, 0);
                any = true;
            }
        }

        sb.append("</hierarchy>");
        return any ? sb.toString() : null;
    }

    private static int rotation(Context ctx) {
        try {
            WindowManager wm = (WindowManager) ctx.getSystemService(Context.WINDOW_SERVICE);
            if (wm != null && wm.getDefaultDisplay() != null) {
                return wm.getDefaultDisplay().getRotation();
            }
        } catch (Exception ignored) {
        }
        return 0;
    }

    private static void dumpNode(AccessibilityNodeInfo node, StringBuilder sb, int index, int depth) {
        if (node == null || depth > MAX_DEPTH) {
            return;
        }
        sb.append("<node");
        attr(sb, "index", Integer.toString(index));
        attr(sb, "text", str(node.getText()));
        attr(sb, "resource-id", node.getViewIdResourceName());
        attr(sb, "class", str(node.getClassName()));
        attr(sb, "package", str(node.getPackageName()));
        attr(sb, "content-desc", str(node.getContentDescription()));
        attr(sb, "checkable", node.isCheckable());
        attr(sb, "checked", node.isChecked());
        attr(sb, "clickable", node.isClickable());
        attr(sb, "enabled", node.isEnabled());
        attr(sb, "focusable", node.isFocusable());
        attr(sb, "focused", node.isFocused());
        attr(sb, "scrollable", node.isScrollable());
        attr(sb, "long-clickable", node.isLongClickable());
        attr(sb, "password", node.isPassword());
        attr(sb, "selected", node.isSelected());

        Rect bounds = new Rect();
        node.getBoundsInScreen(bounds);
        attr(sb, "bounds", "[" + bounds.left + "," + bounds.top + "][" + bounds.right + "," + bounds.bottom + "]");

        int childCount = node.getChildCount();
        if (childCount == 0) {
            sb.append(" />");
            return;
        }
        sb.append(">");
        for (int i = 0; i < childCount; i++) {
            AccessibilityNodeInfo child = null;
            try {
                child = node.getChild(i);
            } catch (Exception ignored) {
            }
            if (child != null) {
                dumpNode(child, sb, i, depth + 1);
            }
        }
        sb.append("</node>");
    }

    private static String str(CharSequence cs) {
        return cs == null ? "" : cs.toString();
    }

    private static void attr(StringBuilder sb, String name, boolean value) {
        sb.append(' ').append(name).append("=\"").append(value ? "true" : "false").append('"');
    }

    private static void attr(StringBuilder sb, String name, String value) {
        sb.append(' ').append(name).append("=\"");
        appendEscaped(sb, value == null ? "" : value);
        sb.append('"');
    }

    /** XML-escape and drop characters that are invalid in XML 1.0. */
    private static void appendEscaped(StringBuilder sb, String s) {
        int n = s.length();
        for (int i = 0; i < n; i++) {
            char c = s.charAt(i);
            switch (c) {
                case '&':
                    sb.append("&amp;");
                    break;
                case '<':
                    sb.append("&lt;");
                    break;
                case '>':
                    sb.append("&gt;");
                    break;
                case '"':
                    sb.append("&quot;");
                    break;
                default:
                    if (c == '\t' || c == '\n' || c == '\r'
                            || (c >= 0x20 && c <= 0xD7FF) || (c >= 0xE000 && c <= 0xFFFD)) {
                        sb.append(c);
                    }
            }
        }
    }
}
