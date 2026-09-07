package com.vyperia.lagswitch;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.res.Configuration;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.net.VpnService;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.provider.Settings;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.view.WindowMetrics;
import android.util.DisplayMetrics;
import android.widget.Button;

import java.io.FileInputStream;
import java.io.IOException;
import java.util.Locale;

public class LagSwitchService extends VpnService {
    public static final String ACTION_TOGGLE = "com.vyperia.lagswitch.TOGGLE";
    public static final String ACTION_ENABLE_OVERLAY = "com.vyperia.lagswitch.ENABLE_OVERLAY";
    public static final String ACTION_DISABLE_OVERLAY = "com.vyperia.lagswitch.DISABLE_OVERLAY";
    public static final String ACTION_RELOAD = "com.vyperia.lagswitch.RELOAD";
    public static final String ACTION_STATE = "com.vyperia.lagswitch.STATE";
    public static final String[] COLOR_NAMES = {"Green", "Red", "Purple", "Blue", "Cyan", "Orange", "Yellow", "Pink", "White", "Gray"};

    private static final String PREFS = "settings";
    private static final int NOTIFICATION_ID = 3108;
    private static final String CHANNEL_ID = "vyperia_lag_switch";

    private final Handler handler = new Handler(Looper.getMainLooper());
    private SharedPreferences prefs;
    private ParcelFileDescriptor tun;
    private Thread discardThread;
    private volatile boolean discardRunning;
    private boolean requestedActive;
    private boolean tunnelActive;
    private boolean paused;
    private WindowManager windowManager;
    private Button overlay;
    private WindowManager.LayoutParams overlayParams;

    private final Runnable activeTimeout = new Runnable() {
        @Override
        public void run() {
            if (!requestedActive || !prefs.getBoolean("anti_timeout", false)) return;
            closeTunnel();
            paused = true;
            broadcastState();
            updateOverlay();
            updateNotification();
            if (prefs.getBoolean("reactivate", false)) {
                long pauseMs = Math.max(100L, Math.round(prefs.getFloat("pause_time", 0.2f) * 1000f));
                handler.postDelayed(pauseFinished, pauseMs);
            } else {
                requestedActive = false;
                paused = false;
                broadcastState();
                updateOverlay();
                updateNotification();
                maybeStop();
            }
        }
    };

    private final Runnable pauseFinished = new Runnable() {
        @Override
        public void run() {
            if (!requestedActive) return;
            paused = false;
            if (openTunnel()) {
                broadcastState();
                updateOverlay();
                updateNotification();
                scheduleActiveTimeout();
            } else {
                requestedActive = false;
                broadcastState();
                updateOverlay();
                updateNotification();
                maybeStop();
            }
        }
    };

    @Override
    public void onCreate() {
        super.onCreate();
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        prefs.edit().putBoolean("runtime_service", true).apply();
        createChannel();
        startForeground(NOTIFICATION_ID, buildNotification());
        if (prefs.getBoolean("overlay_enabled", false) && Settings.canDrawOverlays(this)) {
            showOverlay();
        }
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        handler.postDelayed(this::clampOverlayToScreen, 80L);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startForeground(NOTIFICATION_ID, buildNotification());
        String action = intent == null ? null : intent.getAction();
        if (ACTION_TOGGLE.equals(action)) {
            toggleRequestedState();
        } else if (ACTION_ENABLE_OVERLAY.equals(action)) {
            prefs.edit().putBoolean("overlay_enabled", true).apply();
            showOverlay();
            updateOverlay();
        } else if (ACTION_DISABLE_OVERLAY.equals(action)) {
            prefs.edit().putBoolean("overlay_enabled", false).apply();
            removeOverlay();
            maybeStop();
        } else if (ACTION_RELOAD.equals(action)) {
            reloadSettings();
        }
        broadcastState();
        updateNotification();
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        cancelCycle();
        closeTunnel();
        removeOverlay();
        prefs.edit()
                .putBoolean("runtime_service", false)
                .putBoolean("runtime_requested", false)
                .putBoolean("runtime_active", false)
                .putBoolean("runtime_paused", false)
                .apply();
        super.onDestroy();
    }

    @Override
    public void onRevoke() {
        stopRequestedState();
        super.onRevoke();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return super.onBind(intent);
    }

    private void toggleRequestedState() {
        if (requestedActive) stopRequestedState(); else startRequestedState();
    }

    private void startRequestedState() {
        cancelCycle();
        requestedActive = true;
        paused = false;
        if (!openTunnel()) {
            requestedActive = false;
            tunnelActive = false;
        } else {
            scheduleActiveTimeout();
        }
        broadcastState();
        updateOverlay();
        updateNotification();
    }

    private void stopRequestedState() {
        requestedActive = false;
        paused = false;
        cancelCycle();
        closeTunnel();
        broadcastState();
        updateOverlay();
        updateNotification();
        maybeStop();
    }

    private void reloadSettings() {
        if (prefs.getBoolean("overlay_enabled", false) && Settings.canDrawOverlays(this)) {
            if (overlay == null) showOverlay();
            applyInitialOverlayPositionIfUnset();
            updateOverlay();
        } else {
            removeOverlay();
        }
        if (requestedActive) {
            cancelCycle();
            if (!paused) {
                closeTunnel();
                if (!openTunnel()) requestedActive = false;
            }
            if (requestedActive && !paused) scheduleActiveTimeout();
        }
        broadcastState();
        updateNotification();
        maybeStop();
    }

    private boolean openTunnel() {
        closeTunnel();
        if (VpnService.prepare(this) != null) return false;
        Builder builder = new Builder()
                .setSession("Vyperia Lag Switch")
                .setMtu(1500)
                .addAddress("10.254.0.1", 32)
                .addRoute("0.0.0.0", 0);
        try {
            builder.addAddress("fd00:56:79::1", 128).addRoute("::", 0);
        } catch (Exception ignored) {
        }
        String target = prefs.getString("target_package", "");
        try {
            if (target != null && !target.isEmpty()) {
                builder.addAllowedApplication(target);
            } else {
                builder.addDisallowedApplication(getPackageName());
            }
        } catch (Exception ignored) {
        }
        if (Build.VERSION.SDK_INT >= 29) builder.setMetered(false);
        tun = builder.establish();
        if (tun == null) return false;
        tunnelActive = true;
        startDiscardLoop(tun);
        return true;
    }

    private void startDiscardLoop(ParcelFileDescriptor fd) {
        discardRunning = true;
        discardThread = new Thread(() -> {
            byte[] buffer = new byte[32767];
            try (FileInputStream input = new FileInputStream(fd.getFileDescriptor())) {
                while (discardRunning) {
                    int read = input.read(buffer);
                    if (read < 0) break;
                }
            } catch (IOException ignored) {
            } finally {
                discardRunning = false;
            }
        }, "VyperiaPacketDropper");
        discardThread.start();
    }

    private void closeTunnel() {
        tunnelActive = false;
        discardRunning = false;
        ParcelFileDescriptor current = tun;
        tun = null;
        if (current != null) {
            try {
                current.close();
            } catch (IOException ignored) {
            }
        }
        Thread thread = discardThread;
        discardThread = null;
        if (thread != null) thread.interrupt();
    }

    private void scheduleActiveTimeout() {
        handler.removeCallbacks(activeTimeout);
        handler.removeCallbacks(pauseFinished);
        if (!requestedActive || !prefs.getBoolean("anti_timeout", false)) return;
        long activeMs = Math.max(500L, Math.round(prefs.getFloat("active_time", 9.8f) * 1000f));
        handler.postDelayed(activeTimeout, activeMs);
    }

    private void cancelCycle() {
        handler.removeCallbacks(activeTimeout);
        handler.removeCallbacks(pauseFinished);
    }

    private void showOverlay() {
        if (overlay != null || !Settings.canDrawOverlays(this)) return;
        windowManager = (WindowManager) getSystemService(WINDOW_SERVICE);
        overlay = new Button(this);
        overlay.setAllCaps(false);
        overlay.setTextColor(Color.WHITE);
        overlay.setPadding(dp(14), dp(8), dp(14), dp(8));

        overlayParams = new WindowManager.LayoutParams(
                WindowManager.LayoutParams.WRAP_CONTENT,
                WindowManager.LayoutParams.WRAP_CONTENT,
                Build.VERSION.SDK_INT >= 26 ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY : WindowManager.LayoutParams.TYPE_PHONE,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
                PixelFormat.TRANSLUCENT
        );
        overlayParams.gravity = Gravity.TOP | Gravity.START;
        applyInitialOverlayPositionIfUnset();

        overlay.setOnTouchListener(new View.OnTouchListener() {
            float startTouchX;
            float startTouchY;
            int startX;
            int startY;
            long downAt;
            boolean moved;

            @Override
            public boolean onTouch(View v, MotionEvent event) {
                switch (event.getActionMasked()) {
                    case MotionEvent.ACTION_DOWN:
                        startTouchX = event.getRawX();
                        startTouchY = event.getRawY();
                        startX = overlayParams.x;
                        startY = overlayParams.y;
                        downAt = System.currentTimeMillis();
                        moved = false;
                        return true;
                    case MotionEvent.ACTION_MOVE:
                        if (prefs.getBoolean("overlay_freeze_position", false)) return true;
                        float dx = event.getRawX() - startTouchX;
                        float dy = event.getRawY() - startTouchY;
                        if (Math.abs(dx) > dp(5) || Math.abs(dy) > dp(5)) moved = true;
                        if (moved) {
                            overlayParams.x = startX + Math.round(dx);
                            overlayParams.y = startY + Math.round(dy);
                            clampOverlayCoordinates();
                            try { windowManager.updateViewLayout(overlay, overlayParams); } catch (Exception ignored) {}
                        }
                        return true;
                    case MotionEvent.ACTION_UP:
                        long held = System.currentTimeMillis() - downAt;
                        if (moved) {
                            prefs.edit().putInt("overlay_x", overlayParams.x).putInt("overlay_y", overlayParams.y).apply();
                        } else if (held >= 650) {
                            Intent open = new Intent(LagSwitchService.this, MainActivity.class)
                                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
                            startActivity(open);
                        } else {
                            requestToggleFromOverlay();
                        }
                        return true;
                }
                return false;
            }
        });

        try {
            windowManager.addView(overlay, overlayParams);
            overlay.post(this::clampOverlayToScreen);
        } catch (Exception e) {
            overlay = null;
        }
        updateOverlay();
    }

    private void applyInitialOverlayPositionIfUnset() {
        if (overlayParams == null) return;
        if (prefs.contains("overlay_x") && prefs.contains("overlay_y")) {
            overlayParams.x = prefs.getInt("overlay_x", dp(16));
            overlayParams.y = prefs.getInt("overlay_y", dp(120));
            return;
        }
        int width = getResources().getDisplayMetrics().widthPixels;
        int height = getResources().getDisplayMetrics().heightPixels;
        String position = prefs.getString("overlay_initial_position", "Top Center");
        int margin = dp(18);
        switch (position) {
            case "Top Left": overlayParams.x = margin; overlayParams.y = margin + dp(50); break;
            case "Top Right": overlayParams.x = width - dp(130); overlayParams.y = margin + dp(50); break;
            case "Bottom Left": overlayParams.x = margin; overlayParams.y = height - dp(150); break;
            case "Bottom Right": overlayParams.x = width - dp(130); overlayParams.y = height - dp(150); break;
            case "Bottom Center": overlayParams.x = width / 2 - dp(55); overlayParams.y = height - dp(150); break;
            default: overlayParams.x = width / 2 - dp(55); overlayParams.y = margin + dp(50); break;
        }
    }

    private void updateOverlay() {
        if (overlay == null) return;
        boolean compact = prefs.getBoolean("overlay_compact", false);
        String target = prefs.getString("target_label", "Whole System");
        String text;
        if (paused) text = compact ? "PAUSE" : "Lag PAUSE";
        else if (tunnelActive) text = compact ? "ON" : "Lag ON";
        else text = compact ? "OFF" : "Lag OFF";
        if (!compact && target != null && !target.isEmpty() && !"Whole System".equals(target)) {
            text += "\n" + target;
        }
        overlay.setText(text);
        overlay.setTextSize(prefs.getInt("overlay_text_size", 18));
        String colorName = tunnelActive ? prefs.getString("overlay_on_color", "Green") : prefs.getString("overlay_off_color", "Red");
        if (paused) colorName = "Yellow";
        int backgroundColor = colorFor(colorName);
        if (prefs.getBoolean("overlay_transparent", false)) {
            backgroundColor = Color.argb(90, Color.red(backgroundColor), Color.green(backgroundColor), Color.blue(backgroundColor));
        }
        overlay.setBackgroundTintList(android.content.res.ColorStateList.valueOf(backgroundColor));
        if (windowManager != null && overlayParams != null) {
            overlay.post(this::clampOverlayToScreen);
        }
    }

    private void requestToggleFromOverlay() {
        Intent prepare = VpnService.prepare(this);
        if (prepare != null) {
            Intent permission = new Intent(this, VpnPermissionActivity.class)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_NO_ANIMATION);
            startActivity(permission);
        } else {
            toggleRequestedState();
        }
    }

    private void clampOverlayToScreen() {
        if (overlay == null || overlayParams == null || windowManager == null) return;
        clampOverlayCoordinates();
        try { windowManager.updateViewLayout(overlay, overlayParams); } catch (Exception ignored) {}
        prefs.edit().putInt("overlay_x", overlayParams.x).putInt("overlay_y", overlayParams.y).apply();
    }

    private void clampOverlayCoordinates() {
        if (overlay == null || overlayParams == null || windowManager == null) return;
        int screenWidth;
        int screenHeight;
        if (Build.VERSION.SDK_INT >= 30) {
            WindowMetrics metrics = windowManager.getCurrentWindowMetrics();
            screenWidth = metrics.getBounds().width();
            screenHeight = metrics.getBounds().height();
        } else {
            DisplayMetrics metrics = new DisplayMetrics();
            windowManager.getDefaultDisplay().getRealMetrics(metrics);
            screenWidth = metrics.widthPixels;
            screenHeight = metrics.heightPixels;
        }
        int width = overlay.getWidth() > 0 ? overlay.getWidth() : dp(120);
        int height = overlay.getHeight() > 0 ? overlay.getHeight() : dp(56);
        int margin = dp(4);
        int maxX = Math.max(margin, screenWidth - width - margin);
        int maxY = Math.max(margin, screenHeight - height - margin);
        overlayParams.x = Math.max(margin, Math.min(overlayParams.x, maxX));
        overlayParams.y = Math.max(margin, Math.min(overlayParams.y, maxY));
    }

    private void removeOverlay() {
        if (overlay != null && windowManager != null) {
            try { windowManager.removeView(overlay); } catch (Exception ignored) {}
        }
        overlay = null;
        overlayParams = null;
    }

    private void broadcastState() {
        prefs.edit()
                .putBoolean("runtime_requested", requestedActive)
                .putBoolean("runtime_active", tunnelActive)
                .putBoolean("runtime_paused", paused)
                .putBoolean("runtime_service", true)
                .apply();
        Intent state = new Intent(ACTION_STATE)
                .setPackage(getPackageName())
                .putExtra("requested", requestedActive)
                .putExtra("active", tunnelActive)
                .putExtra("paused", paused);
        sendBroadcast(state);
    }

    private void maybeStop() {
        boolean overlayEnabled = prefs.getBoolean("overlay_enabled", false) && Settings.canDrawOverlays(this);
        if (!requestedActive && !overlayEnabled) {
            stopForeground(STOP_FOREGROUND_REMOVE);
            stopSelf();
        }
    }

    private void createChannel() {
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        NotificationChannel channel = new NotificationChannel(CHANNEL_ID, "Vyperia Lag Switch", NotificationManager.IMPORTANCE_LOW);
        channel.setDescription("Lag switch and floating overlay controller");
        manager.createNotificationChannel(channel);
    }

    private Notification buildNotification() {
        Intent openIntent = new Intent(this, MainActivity.class);
        PendingIntent openPending = PendingIntent.getActivity(this, 1, openIntent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        PendingIntent togglePending;
        if (!requestedActive && VpnService.prepare(this) != null) {
            Intent permissionIntent = new Intent(this, VpnPermissionActivity.class);
            togglePending = PendingIntent.getActivity(this, 2, permissionIntent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        } else {
            Intent toggleIntent = new Intent(this, LagSwitchService.class).setAction(ACTION_TOGGLE);
            togglePending = PendingIntent.getService(this, 2, toggleIntent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        }
        String target = prefs == null ? "Whole System" : prefs.getString("target_label", "Whole System");
        String state = paused ? "Cycle pause" : tunnelActive ? "Lag ON" : "Lag OFF";
        return new Notification.Builder(this, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.stat_sys_warning)
                .setContentTitle("Vyperia Lag Switch — " + state)
                .setContentText(target)
                .setContentIntent(openPending)
                .setOngoing(requestedActive || (prefs != null && prefs.getBoolean("overlay_enabled", false)))
                .addAction(new Notification.Action.Builder(android.R.drawable.ic_media_pause, requestedActive ? "Turn Off" : "Turn On", togglePending).build())
                .build();
    }

    private void updateNotification() {
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        manager.notify(NOTIFICATION_ID, buildNotification());
    }

    public static int colorFor(String name) {
        if (name == null) name = "Purple";
        switch (name.toLowerCase(Locale.ROOT)) {
            case "green": return Color.rgb(34, 197, 94);
            case "red": return Color.rgb(225, 29, 72);
            case "blue": return Color.rgb(37, 99, 235);
            case "cyan": return Color.rgb(6, 182, 212);
            case "orange": return Color.rgb(234, 88, 12);
            case "yellow": return Color.rgb(202, 138, 4);
            case "pink": return Color.rgb(219, 39, 119);
            case "white": return Color.rgb(226, 232, 240);
            case "gray": return Color.rgb(100, 116, 139);
            default: return Color.rgb(147, 51, 234);
        }
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
