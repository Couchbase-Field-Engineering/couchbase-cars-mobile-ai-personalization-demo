import { Stack } from 'expo-router';
import { useEffect } from 'react';
import { Platform } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { DataProvider } from '@/src/data/DataContext';
import { AuthProvider } from '@/src/session/AuthContext';
import { theme } from '@/src/theme';
import { DeviceFrame } from '@/src/ui/DeviceFrame';

const INTER = 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700;800&display=swap';

export default function RootLayout() {
  // couchbase.com sets its type in Inter; load it for the browser build.
  useEffect(() => {
    if (Platform.OS !== 'web' || document.getElementById('inter-font')) return;
    const link = document.createElement('link');
    link.id = 'inter-font';
    link.rel = 'stylesheet';
    link.href = INTER;
    document.head.appendChild(link);
    document.body.style.fontFamily = "Inter, -apple-system, 'Helvetica Neue', Arial, sans-serif";
  }, []);
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <DataProvider>
          <DeviceFrame>
            <StatusBar style="light" />
            <Stack
              screenOptions={{
                headerStyle: { backgroundColor: theme.color.navy },
                headerTintColor: theme.color.onDark,
                headerTitleStyle: { fontWeight: '800' },
                contentStyle: { backgroundColor: theme.color.bg },
              }}
            >
              <Stack.Screen name="index" options={{ headerShown: false }} />
              <Stack.Screen name="login" options={{ headerShown: false }} />
              <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
              <Stack.Screen name="upgrade" options={{ title: 'Upgrade your vehicle', presentation: 'modal' }} />
              <Stack.Screen name="protection" options={{ title: 'Protection', presentation: 'modal' }} />
              <Stack.Screen name="service" options={{ title: 'Couchbase Cars Services', presentation: 'modal' }} />
              <Stack.Screen name="checkin" options={{ title: 'Mobile check-in', presentation: 'modal' }} />
              <Stack.Screen name="confirm" options={{ title: 'Review & confirm', presentation: 'modal' }} />
            </Stack>
          </DeviceFrame>
        </DataProvider>
      </AuthProvider>
    </SafeAreaProvider>
  );
}
