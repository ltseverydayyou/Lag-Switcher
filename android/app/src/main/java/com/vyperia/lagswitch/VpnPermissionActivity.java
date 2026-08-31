package com.vyperia.lagswitch;

import android.app.Activity;
import android.content.Intent;
import android.net.VpnService;
import android.os.Build;
import android.os.Bundle;
import android.widget.Toast;

public class VpnPermissionActivity extends Activity {
    private static final int REQ_VPN = 2001;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        requestVpnPermission();
    }

    private void requestVpnPermission() {
        Intent prepare = VpnService.prepare(this);
        if (prepare == null) {
            toggleLagSwitch();
            finish();
            return;
        }
        startActivityForResult(prepare, REQ_VPN);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQ_VPN) return;
        if (resultCode == RESULT_OK) {
            toggleLagSwitch();
        } else {
            Toast.makeText(this, "VPN permission is required for the lag switch.", Toast.LENGTH_LONG).show();
        }
        finish();
    }

    private void toggleLagSwitch() {
        Intent intent = new Intent(this, LagSwitchService.class).setAction(LagSwitchService.ACTION_TOGGLE);
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(intent); else startService(intent);
    }
}
