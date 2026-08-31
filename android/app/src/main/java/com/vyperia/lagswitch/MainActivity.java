package com.vyperia.lagswitch;

import android.Manifest;
import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.drawable.Drawable;
import android.net.VpnService;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.BaseAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.SeekBar;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;

public class MainActivity extends Activity {
    private static final int REQ_VPN = 1001;
    private static final int REQ_OVERLAY = 1002;
    private static final int REQ_NOTIFICATIONS = 1003;
    private static final String PREFS = "settings";
    private static final int BG = Color.rgb(16, 11, 22);
    private static final int PANEL = Color.rgb(29, 20, 39);
    private static final int TEXT = Color.rgb(244, 238, 250);
    private static final int MUTED = Color.rgb(187, 171, 201);
    private static final int ACCENT = Color.rgb(168, 85, 247);
    private static final int ON = Color.rgb(52, 211, 153);
    private static final int OFF = Color.rgb(251, 113, 133);

    private final List<AppEntry> apps = new ArrayList<>();
    private SharedPreferences prefs;
    private TextView status;
    private Button toggle;
    private Button overlayButton;
    private Spinner appSpinner;
    private Spinner onColorSpinner;
    private Spinner offColorSpinner;
    private Spinner initialPositionSpinner;
    private CheckBox antiTimeout;
    private CheckBox reactivate;
    private CheckBox compactOverlay;
    private TextView activeTimeLabel;
    private TextView pauseTimeLabel;
    private TextView overlaySizeLabel;
    private boolean pendingToggle;

    private final BroadcastReceiver stateReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (!LagSwitchService.ACTION_STATE.equals(intent.getAction())) return;
            boolean requested = intent.getBooleanExtra("requested", false);
            boolean active = intent.getBooleanExtra("active", false);
            boolean paused = intent.getBooleanExtra("paused", false);
            updateStatus(requested, active, paused);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        buildUi();
        loadApps();
        loadSettingsIntoUi();
        maybeRequestNotificationPermission();
    }

    @Override
    protected void onStart() {
        super.onStart();
        IntentFilter filter = new IntentFilter(LagSwitchService.ACTION_STATE);
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(stateReceiver, filter, Context.RECEIVER_NOT_EXPORTED);
        } else {
            registerReceiver(stateReceiver, filter);
        }
        updateStatus(
                prefs.getBoolean("runtime_requested", false),
                prefs.getBoolean("runtime_active", false),
                prefs.getBoolean("runtime_paused", false)
        );
    }

    @Override
    protected void onStop() {
        super.onStop();
        try {
            unregisterReceiver(stateReceiver);
        } catch (Exception ignored) {
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        boolean wanted = prefs.getBoolean("overlay_enabled", false);
        if (wanted && Settings.canDrawOverlays(this)) {
            sendService(LagSwitchService.ACTION_ENABLE_OVERLAY);
            if (overlayButton != null) overlayButton.setText("Disable floating button");
        } else if (overlayButton != null) {
            overlayButton.setText("Enable floating button");
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_VPN && resultCode == RESULT_OK && pendingToggle) {
            pendingToggle = false;
            sendService(LagSwitchService.ACTION_TOGGLE);
        } else if (requestCode == REQ_VPN) {
            pendingToggle = false;
            Toast.makeText(this, "VPN permission is required for the lag switch.", Toast.LENGTH_LONG).show();
        }
    }

    private void buildUi() {
        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(BG);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(18), dp(18), dp(18), dp(32));
        scroll.addView(root);

        TextView title = text("Vyperia Lag Switch", 28, TEXT);
        title.setTypeface(title.getTypeface(), 1);
        root.addView(title);
        TextView subtitle = text("Android VPN-based app or system connection toggle", 14, MUTED);
        subtitle.setPadding(0, dp(2), 0, dp(18));
        root.addView(subtitle);

        LinearLayout statusCard = card();
        status = text("Lag Switch Off", 22, OFF);
        status.setTypeface(status.getTypeface(), 1);
        status.setGravity(Gravity.CENTER_HORIZONTAL);
        statusCard.addView(status);
        toggle = button("Turn On");
        toggle.setOnClickListener(v -> requestToggle());
        statusCard.addView(toggle, matchWrap(dp(52), dp(10)));
        root.addView(statusCard, fullWidth(dp(12)));

        LinearLayout targetCard = card();
        targetCard.addView(sectionTitle("Target"));
        appSpinner = spinner();
        targetCard.addView(appSpinner, matchWrap(dp(48), dp(8)));
        Button refresh = button("Refresh Apps");
        refresh.setOnClickListener(v -> {
            saveTargetSelection();
            loadApps();
            selectSavedTarget();
        });
        targetCard.addView(refresh, matchWrap(dp(46), dp(0)));
        TextView targetInfo = text("Whole System blocks traffic for every app. Selecting an app only blackholes that package through Android's VPN routing.", 13, MUTED);
        targetInfo.setPadding(0, dp(10), 0, 0);
        targetCard.addView(targetInfo);
        root.addView(targetCard, fullWidth(dp(12)));

        LinearLayout cycleCard = card();
        cycleCard.addView(sectionTitle("Lag behavior"));
        antiTimeout = checkbox("Anti-timeout cycle");
        reactivate = checkbox("Reactivate after pause");
        antiTimeout.setOnCheckedChangeListener((b, checked) -> {
            prefs.edit().putBoolean("anti_timeout", checked).apply();
            reactivate.setEnabled(checked);
            sendServiceIfRunning(LagSwitchService.ACTION_RELOAD);
        });
        reactivate.setOnCheckedChangeListener((b, checked) -> {
            prefs.edit().putBoolean("reactivate", checked).apply();
            sendServiceIfRunning(LagSwitchService.ACTION_RELOAD);
        });
        cycleCard.addView(antiTimeout);
        cycleCard.addView(reactivate);

        activeTimeLabel = text("Active time", 14, TEXT);
        cycleCard.addView(activeTimeLabel);
        SeekBar activeSeek = seek(5, 100);
        activeSeek.setProgress((int) Math.round(prefs.getFloat("active_time", 9.8f) * 10f));
        activeSeek.setOnSeekBarChangeListener(simpleSeek(progress -> {
            float value = Math.max(0.5f, progress / 10f);
            prefs.edit().putFloat("active_time", value).apply();
            activeTimeLabel.setText(String.format(Locale.US, "Active time: %.1fs", value));
            sendServiceIfRunning(LagSwitchService.ACTION_RELOAD);
        }));
        cycleCard.addView(activeSeek);

        pauseTimeLabel = text("Pause time", 14, TEXT);
        cycleCard.addView(pauseTimeLabel);
        SeekBar pauseSeek = seek(1, 30);
        pauseSeek.setProgress((int) Math.round(prefs.getFloat("pause_time", 0.2f) * 10f));
        pauseSeek.setOnSeekBarChangeListener(simpleSeek(progress -> {
            float value = Math.max(0.1f, progress / 10f);
            prefs.edit().putFloat("pause_time", value).apply();
            pauseTimeLabel.setText(String.format(Locale.US, "Pause time: %.1fs", value));
            sendServiceIfRunning(LagSwitchService.ACTION_RELOAD);
        }));
        cycleCard.addView(pauseSeek);
        root.addView(cycleCard, fullWidth(dp(12)));

        LinearLayout overlayCard = card();
        overlayCard.addView(sectionTitle("Floating button"));
        overlayButton = button("Enable floating button");
        overlayButton.setOnClickListener(v -> toggleOverlay());
        overlayCard.addView(overlayButton, matchWrap(dp(48), dp(8)));

        compactOverlay = checkbox("Compact overlay text");
        compactOverlay.setOnCheckedChangeListener((b, checked) -> {
            prefs.edit().putBoolean("overlay_compact", checked).apply();
            sendServiceIfRunning(LagSwitchService.ACTION_RELOAD);
        });
        overlayCard.addView(compactOverlay);

        overlaySizeLabel = text("Overlay text size", 14, TEXT);
        overlayCard.addView(overlaySizeLabel);
        SeekBar sizeSeek = seek(12, 36);
        sizeSeek.setProgress(prefs.getInt("overlay_text_size", 18));
        sizeSeek.setOnSeekBarChangeListener(simpleSeek(progress -> {
            int value = Math.max(12, progress);
            prefs.edit().putInt("overlay_text_size", value).apply();
            overlaySizeLabel.setText("Overlay text size: " + value + "sp");
            sendServiceIfRunning(LagSwitchService.ACTION_RELOAD);
        }));
        overlayCard.addView(sizeSeek);

        overlayCard.addView(text("Initial overlay position", 14, TEXT));
        initialPositionSpinner = spinner();
        String[] positions = {"Top Center", "Top Left", "Top Right", "Bottom Center", "Bottom Left", "Bottom Right"};
        initialPositionSpinner.setAdapter(simpleAdapter(positions));
        initialPositionSpinner.setOnItemSelectedListener(new SimpleItemSelectedListener(position -> {
            prefs.edit().putString("overlay_initial_position", positions[position]).remove("overlay_x").remove("overlay_y").apply();
            sendServiceIfRunning(LagSwitchService.ACTION_RELOAD);
        }));
        overlayCard.addView(initialPositionSpinner, matchWrap(dp(48), dp(8)));

        overlayCard.addView(text("Overlay ON color", 14, TEXT));
        onColorSpinner = spinner();
        overlayCard.addView(onColorSpinner, matchWrap(dp(48), dp(8)));
        overlayCard.addView(text("Overlay OFF color", 14, TEXT));
        offColorSpinner = spinner();
        overlayCard.addView(offColorSpinner, matchWrap(dp(48), dp(8)));
        String[] colors = LagSwitchService.COLOR_NAMES;
        onColorSpinner.setAdapter(simpleAdapter(colors));
        offColorSpinner.setAdapter(simpleAdapter(colors));
        onColorSpinner.setOnItemSelectedListener(new SimpleItemSelectedListener(position -> {
            prefs.edit().putString("overlay_on_color", colors[position]).apply();
            sendServiceIfRunning(LagSwitchService.ACTION_RELOAD);
        }));
        offColorSpinner.setOnItemSelectedListener(new SimpleItemSelectedListener(position -> {
            prefs.edit().putString("overlay_off_color", colors[position]).apply();
            sendServiceIfRunning(LagSwitchService.ACTION_RELOAD);
        }));

        TextView hint = text("Tap the floating button to toggle. Drag it anywhere. Long-press it to reopen this screen.", 13, MUTED);
        hint.setPadding(0, dp(10), 0, 0);
        overlayCard.addView(hint);
        root.addView(overlayCard, fullWidth(dp(12)));

        LinearLayout infoCard = card();
        infoCard.addView(sectionTitle("How it works"));
        infoCard.addView(text("When enabled, Android routes the selected traffic into a local VPN TUN interface. Vyperia Lag Switch reads and discards those packets instead of disabling Wi-Fi or mobile data. Turning it off closes the TUN and normal routing resumes.", 13, MUTED));
        root.addView(infoCard, fullWidth(0));

        setContentView(scroll);
    }

    private void loadSettingsIntoUi() {
        antiTimeout.setChecked(prefs.getBoolean("anti_timeout", false));
        reactivate.setChecked(prefs.getBoolean("reactivate", false));
        reactivate.setEnabled(antiTimeout.isChecked());
        compactOverlay.setChecked(prefs.getBoolean("overlay_compact", false));
        float active = prefs.getFloat("active_time", 9.8f);
        float pause = prefs.getFloat("pause_time", 0.2f);
        activeTimeLabel.setText(String.format(Locale.US, "Active time: %.1fs", active));
        pauseTimeLabel.setText(String.format(Locale.US, "Pause time: %.1fs", pause));
        overlaySizeLabel.setText("Overlay text size: " + prefs.getInt("overlay_text_size", 18) + "sp");
        setSpinnerSelection(initialPositionSpinner, new String[]{"Top Center", "Top Left", "Top Right", "Bottom Center", "Bottom Left", "Bottom Right"}, prefs.getString("overlay_initial_position", "Top Center"));
        setSpinnerSelection(onColorSpinner, LagSwitchService.COLOR_NAMES, prefs.getString("overlay_on_color", "Green"));
        setSpinnerSelection(offColorSpinner, LagSwitchService.COLOR_NAMES, prefs.getString("overlay_off_color", "Red"));
        overlayButton.setText(prefs.getBoolean("overlay_enabled", false) && Settings.canDrawOverlays(this) ? "Disable floating button" : "Enable floating button");
    }

    private void loadApps() {
        apps.clear();
        PackageManager pm = getPackageManager();
        Drawable systemIcon;
        try {
            systemIcon = getDrawable(android.R.drawable.ic_menu_manage);
        } catch (Exception e) {
            systemIcon = null;
        }
        apps.add(new AppEntry("Whole System", "", systemIcon));
        if (Build.VERSION.SDK_INT >= 33) {
            List<ApplicationInfo> installed = pm.getInstalledApplications(PackageManager.ApplicationInfoFlags.of(0));
            addInstalledApps(pm, installed);
        } else {
            addInstalledApps(pm, pm.getInstalledApplications(0));
        }
        Collections.sort(apps.subList(1, apps.size()), Comparator.comparing(a -> a.label.toLowerCase(Locale.ROOT)));
        appSpinner.setAdapter(new AppSpinnerAdapter());
        appSpinner.setOnItemSelectedListener(new SimpleItemSelectedListener(position -> {
            AppEntry e = apps.get(position);
            prefs.edit().putString("target_package", e.pkg).putString("target_label", e.label).apply();
            sendServiceIfRunning(LagSwitchService.ACTION_RELOAD);
        }));
        selectSavedTarget();
    }

    private void addInstalledApps(PackageManager pm, List<ApplicationInfo> installed) {
        for (ApplicationInfo ai : installed) {
            if (ai.packageName.equals(getPackageName())) continue;
            if (pm.getLaunchIntentForPackage(ai.packageName) == null) continue;
            String label = String.valueOf(pm.getApplicationLabel(ai));
            Drawable icon;
            try {
                icon = ai.loadIcon(pm);
            } catch (Exception e) {
                icon = null;
            }
            apps.add(new AppEntry(label, ai.packageName, icon));
        }
    }

    private void selectSavedTarget() {
        String saved = prefs.getString("target_package", "");
        for (int i = 0; i < apps.size(); i++) {
            if (apps.get(i).pkg.equals(saved)) {
                appSpinner.setSelection(i);
                return;
            }
        }
        appSpinner.setSelection(0);
    }

    private void saveTargetSelection() {
        int position = appSpinner.getSelectedItemPosition();
        if (position >= 0 && position < apps.size()) {
            AppEntry e = apps.get(position);
            prefs.edit().putString("target_package", e.pkg).putString("target_label", e.label).apply();
        }
    }

    private void requestToggle() {
        saveTargetSelection();
        Intent prepare = VpnService.prepare(this);
        if (prepare != null) {
            pendingToggle = true;
            startActivityForResult(prepare, REQ_VPN);
            return;
        }
        sendService(LagSwitchService.ACTION_TOGGLE);
    }

    private void toggleOverlay() {
        boolean enabled = prefs.getBoolean("overlay_enabled", false) && Settings.canDrawOverlays(this);
        if (enabled) {
            prefs.edit().putBoolean("overlay_enabled", false).apply();
            sendService(LagSwitchService.ACTION_DISABLE_OVERLAY);
            overlayButton.setText("Enable floating button");
            return;
        }
        prefs.edit().putBoolean("overlay_enabled", true).apply();
        if (!Settings.canDrawOverlays(this)) {
            Intent intent = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:" + getPackageName()));
            startActivityForResult(intent, REQ_OVERLAY);
        } else {
            sendService(LagSwitchService.ACTION_ENABLE_OVERLAY);
            overlayButton.setText("Disable floating button");
        }
    }

    private void updateStatus(boolean requested, boolean active, boolean paused) {
        if (!requested) {
            status.setText("Lag Switch Off");
            status.setTextColor(OFF);
            toggle.setText("Turn On");
        } else if (paused) {
            status.setText("Cycle Pause");
            status.setTextColor(Color.rgb(250, 204, 21));
            toggle.setText("Turn Off");
        } else if (active) {
            status.setText("Lag Switch On");
            status.setTextColor(ON);
            toggle.setText("Turn Off");
        } else {
            status.setText("Starting…");
            status.setTextColor(Color.rgb(192, 132, 252));
            toggle.setText("Turn Off");
        }
    }

    private void sendService(String action) {
        Intent intent = new Intent(this, LagSwitchService.class).setAction(action);
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(intent); else startService(intent);
    }

    private void sendServiceIfRunning(String action) {
        if (prefs.getBoolean("runtime_service", false) || prefs.getBoolean("overlay_enabled", false) || prefs.getBoolean("runtime_requested", false)) {
            sendService(action);
        }
    }

    private void maybeRequestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, REQ_NOTIFICATIONS);
        }
    }

    private LinearLayout card() {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(dp(16), dp(16), dp(16), dp(16));
        layout.setBackgroundColor(PANEL);
        return layout;
    }

    private TextView sectionTitle(String value) {
        TextView t = text(value, 18, TEXT);
        t.setTypeface(t.getTypeface(), 1);
        t.setPadding(0, 0, 0, dp(10));
        return t;
    }

    private TextView text(String value, int sp, int color) {
        TextView t = new TextView(this);
        t.setText(value);
        t.setTextSize(sp);
        t.setTextColor(color);
        return t;
    }

    private Button button(String value) {
        Button b = new Button(this);
        b.setText(value);
        b.setTextColor(Color.WHITE);
        b.setBackgroundTintList(android.content.res.ColorStateList.valueOf(ACCENT));
        return b;
    }

    private CheckBox checkbox(String value) {
        CheckBox c = new CheckBox(this);
        c.setText(value);
        c.setTextColor(TEXT);
        c.setButtonTintList(android.content.res.ColorStateList.valueOf(ACCENT));
        return c;
    }

    private Spinner spinner() {
        Spinner s = new Spinner(this);
        s.setBackgroundTintList(android.content.res.ColorStateList.valueOf(Color.rgb(126, 74, 160)));
        return s;
    }

    private ArrayAdapter<String> simpleAdapter(String[] values) {
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, values);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        return adapter;
    }

    private SeekBar seek(int min, int max) {
        SeekBar s = new SeekBar(this);
        if (Build.VERSION.SDK_INT >= 26) s.setMin(min);
        s.setMax(max);
        s.setProgressTintList(android.content.res.ColorStateList.valueOf(ACCENT));
        s.setThumbTintList(android.content.res.ColorStateList.valueOf(Color.rgb(216, 180, 254)));
        return s;
    }

    private SeekBar.OnSeekBarChangeListener simpleSeek(IntConsumer consumer) {
        return new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) { if (fromUser) consumer.accept(progress); }
            @Override public void onStartTrackingTouch(SeekBar seekBar) {}
            @Override public void onStopTrackingTouch(SeekBar seekBar) {}
        };
    }

    private void setSpinnerSelection(Spinner spinner, String[] values, String wanted) {
        for (int i = 0; i < values.length; i++) {
            if (values[i].equals(wanted)) {
                spinner.setSelection(i);
                return;
            }
        }
        spinner.setSelection(0);
    }

    private LinearLayout.LayoutParams fullWidth(int bottomMargin) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.bottomMargin = bottomMargin;
        return lp;
    }

    private LinearLayout.LayoutParams matchWrap(int height, int bottomMargin) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, height);
        lp.bottomMargin = bottomMargin;
        return lp;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private final class AppSpinnerAdapter extends BaseAdapter implements android.widget.SpinnerAdapter {
        @Override public int getCount() { return apps.size(); }
        @Override public Object getItem(int position) { return apps.get(position); }
        @Override public long getItemId(int position) { return position; }
        @Override public View getView(int position, View convertView, ViewGroup parent) { return appRow(position, false); }
        @Override public View getDropDownView(int position, View convertView, ViewGroup parent) { return appRow(position, true); }

        private View appRow(int position, boolean dropdown) {
            AppEntry entry = apps.get(position);
            LinearLayout row = new LinearLayout(MainActivity.this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setGravity(Gravity.CENTER_VERTICAL);
            row.setPadding(dp(10), dp(dropdown ? 9 : 6), dp(10), dp(dropdown ? 9 : 6));
            row.setBackgroundColor(dropdown ? PANEL : Color.TRANSPARENT);

            ImageView icon = new ImageView(MainActivity.this);
            icon.setScaleType(ImageView.ScaleType.FIT_CENTER);
            if (entry.icon != null) icon.setImageDrawable(entry.icon);
            LinearLayout.LayoutParams iconLp = new LinearLayout.LayoutParams(dp(38), dp(38));
            iconLp.rightMargin = dp(12);
            row.addView(icon, iconLp);

            LinearLayout labels = new LinearLayout(MainActivity.this);
            labels.setOrientation(LinearLayout.VERTICAL);
            TextView name = text(entry.label, 15, TEXT);
            name.setSingleLine(true);
            labels.addView(name);
            if (!entry.pkg.isEmpty()) {
                TextView pkg = text(entry.pkg, 11, MUTED);
                pkg.setSingleLine(true);
                labels.addView(pkg);
            }
            row.addView(labels, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
            return row;
        }
    }

    private static final class AppEntry {
        final String label;
        final String pkg;
        final Drawable icon;
        AppEntry(String label, String pkg, Drawable icon) { this.label = label; this.pkg = pkg; this.icon = icon; }
    }

    private interface IntConsumer { void accept(int value); }

    private static final class SimpleItemSelectedListener implements android.widget.AdapterView.OnItemSelectedListener {
        private final IntConsumer consumer;
        SimpleItemSelectedListener(IntConsumer consumer) { this.consumer = consumer; }
        @Override public void onItemSelected(android.widget.AdapterView<?> parent, View view, int position, long id) { consumer.accept(position); }
        @Override public void onNothingSelected(android.widget.AdapterView<?> parent) {}
    }
}
