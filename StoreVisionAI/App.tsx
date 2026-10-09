import React, {useState} from 'react';
import {ActivityIndicator, Alert, Image, PermissionsAndroid, Platform, Pressable, SafeAreaView, ScrollView, StatusBar, StyleSheet, Text, View} from 'react-native';
import {Asset, launchCamera, launchImageLibrary} from 'react-native-image-picker';

// Android Emulator reaches the development machine through 10.0.2.2.
// For a physical phone, set USE_LAN_SERVER to true and replace this address
// with this computer's LAN IPv4 address (both devices must share the network).
const USE_LAN_SERVER = false;
const LAN_SERVER_IP = '192.168.1.100';
const API_HOST = USE_LAN_SERVER ? LAN_SERVER_IP : '10.0.2.2';
const API_URL = `http://${API_HOST}:8000/api/audit-shelf`;
type AuditResult = {shelf_health_score: number; items_detected: number; empty_slots: number; restock_required: boolean; detection_uncertain: boolean; agent_log: string[]; annotated_image: string};

async function requestCameraPermission(): Promise<boolean> {
  if (Platform.OS !== 'android') return true;
  const result = await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.CAMERA, {
    title: 'Camera access', message: 'StoreVision AI uses the camera to audit shelf availability.', buttonPositive: 'Allow', buttonNegative: 'Not now',
  });
  return result === PermissionsAndroid.RESULTS.GRANTED;
}

function App() {
  const [sourceUri, setSourceUri] = useState<string>();
  const [result, setResult] = useState<AuditResult>();
  const [isAnalysing, setIsAnalysing] = useState(false);
  const [traceOpen, setTraceOpen] = useState(false);

  const auditAsset = async (asset?: Asset) => {
    if (!asset?.uri) return;
    setSourceUri(asset.uri); setResult(undefined); setTraceOpen(false); setIsAnalysing(true);
    let response: Response | undefined;
    try {
      const formData = new FormData();
      formData.append('file', {
        uri: Platform.OS === 'android' ? asset.uri : asset.uri.replace('file://', ''),
        type: asset.type || 'image/jpeg',
        name: asset.fileName || 'shelf_scan.jpg',
      } as any);
      console.log('[StoreVision AI] Uploading shelf image', {endpoint: API_URL, uri: asset.uri});
      response = await fetch(API_URL, {
        method: 'POST',
        headers: {'Content-Type': 'multipart/form-data'},
        body: formData,
      });
      const body = await response.json();
      if (!response.ok) {
        console.error('[StoreVision AI] API rejected shelf audit', {endpoint: API_URL, status: response.status, body});
        throw new Error(body.detail ?? `Shelf audit failed with HTTP ${response.status}.`);
      }
      setResult(body as AuditResult);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Please check that the backend is running.';
      console.error('[StoreVision AI] Shelf audit network request failed', {
        endpoint: API_URL,
        message,
        responseStatus: response?.status ?? 'No response received',
      });
      Alert.alert('Analysis unavailable', `${message}\n\nEndpoint: ${API_URL}`);
    } finally { setIsAnalysing(false); }
  };

  const takePhoto = async () => {
    if (!(await requestCameraPermission())) { Alert.alert('Camera permission required', 'Enable camera access to capture a shelf photo.'); return; }
    const response = await launchCamera({mediaType: 'photo', quality: 0.8, saveToPhotos: false});
    if (response.errorMessage) Alert.alert('Camera error', response.errorMessage); else await auditAsset(response.assets?.[0]);
  };
  const choosePhoto = async () => {
    const response = await launchImageLibrary({mediaType: 'photo', quality: 0.8, selectionLimit: 1});
    if (response.errorMessage) Alert.alert('Photo library error', response.errorMessage); else await auditAsset(response.assets?.[0]);
  };
  const shownImage = result?.annotated_image ?? sourceUri;

  return <SafeAreaView style={styles.safeArea}>
    <StatusBar barStyle="light-content" />
    <ScrollView contentContainerStyle={styles.content}>
      <View style={styles.header}><Text style={styles.eyebrow}>AGENTIC RETAIL INTELLIGENCE</Text><Text style={styles.title}>StoreVision AI</Text><Text style={styles.subtitle}>Capture a shelf. Let the agent find the gaps.</Text></View>
      <View style={styles.viewer}>
        {shownImage ? <Image source={{uri: shownImage}} style={styles.shelfImage} resizeMode="cover" /> : <View style={styles.emptyViewer}><Text style={styles.viewerIcon}>▣</Text><Text style={styles.emptyTitle}>Shelf scan ready</Text><Text style={styles.emptyText}>Take a clear, front-facing photo to begin an audit.</Text></View>}
        {isAnalysing && <View style={styles.loadingOverlay}><ActivityIndicator color="#7CF5B1" size="large" /><Text style={styles.loadingText}>Agent is inspecting shelf geometry…</Text></View>}
      </View>
      <View style={styles.actions}>
        <Pressable style={[styles.actionButton, styles.primaryButton]} onPress={takePhoto} disabled={isAnalysing}><Text style={styles.primaryButtonText}>◉  Capture shelf</Text></Pressable>
        <Pressable style={styles.actionButton} onPress={choosePhoto} disabled={isAnalysing}><Text style={styles.secondaryButtonText}>▧  Choose photo</Text></Pressable>
      </View>
      {result && <View style={styles.auditCard}>
        <View style={styles.cardHeader}><View><Text style={styles.cardLabel}>LATEST AUDIT</Text><Text style={[styles.status, result.detection_uncertain ? styles.warning : result.restock_required ? styles.danger : styles.healthy]}>{result.detection_uncertain ? 'DETECTION UNCERTAIN' : result.restock_required ? 'RESTOCK ATTENTION' : 'SHELF HEALTHY'}</Text></View><Text style={styles.score}>{result.detection_uncertain ? '—' : result.shelf_health_score}<Text style={styles.scoreUnit}>{result.detection_uncertain ? '' : '/100'}</Text></Text></View>
        <View style={styles.metrics}><Metric value={result.items_detected} label="ITEMS FOUND" /><Metric value={result.empty_slots} label="MISSING SLOTS" danger={result.empty_slots > 0} /><Metric value={`${result.shelf_health_score}%`} label="HEALTH SCORE" /></View>
        <Pressable style={styles.traceButton} onPress={() => setTraceOpen(open => !open)}><Text style={styles.traceTitle}>Agent Decision Trace</Text><Text style={styles.chevron}>{traceOpen ? '⌃' : '⌄'}</Text></Pressable>
        {traceOpen && <View style={styles.trace}>{result.agent_log.map((line, index) => <Text key={`${line}-${index}`} style={styles.traceLine}>• {line}</Text>)}</View>}
      </View>}
    </ScrollView>
  </SafeAreaView>;
}

function Metric({value, label, danger = false}: {value: string | number; label: string; danger?: boolean}) { return <View style={styles.metric}><Text style={[styles.metricValue, danger && styles.danger]}>{value}</Text><Text style={styles.metricLabel}>{label}</Text></View>; }

const styles = StyleSheet.create({
  safeArea: {flex: 1, backgroundColor: '#0B131B'}, content: {paddingHorizontal: 20, paddingBottom: 40}, header: {paddingTop: Platform.OS === 'android' ? (StatusBar.currentHeight || 24) + 12 : 12, marginBottom: 24}, eyebrow: {color: '#72DDA2', fontSize: 11, fontWeight: '800', letterSpacing: 1.7}, title: {color: '#F4FAF7', fontSize: 34, fontWeight: '800', marginTop: 6}, subtitle: {color: '#9CB0B3', fontSize: 15, marginTop: 5},
  viewer: {height: 290, borderRadius: 22, backgroundColor: '#10252C', overflow: 'hidden', borderWidth: 1, borderColor: '#1D3A40'}, shelfImage: {width: '100%', height: '100%'}, emptyViewer: {alignItems: 'center', justifyContent: 'center', flex: 1, padding: 30}, viewerIcon: {fontSize: 42, color: '#72DDA2'}, emptyTitle: {color: '#EAF4EF', fontSize: 19, fontWeight: '700', marginTop: 10}, emptyText: {color: '#91A8AA', textAlign: 'center', lineHeight: 20, marginTop: 7}, loadingOverlay: {position: 'absolute', inset: 0, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(2,14,18,0.82)'}, loadingText: {color: '#D8EEE2', marginTop: 14, fontWeight: '600'},
  actions: {flexDirection: 'row', gap: 12, marginTop: 14}, actionButton: {flex: 1, alignItems: 'center', paddingVertical: 15, borderRadius: 13, borderWidth: 1, borderColor: '#31545A', backgroundColor: '#10252C'}, primaryButton: {backgroundColor: '#71E3A1', borderColor: '#71E3A1'}, primaryButtonText: {color: '#072118', fontWeight: '800'}, secondaryButtonText: {color: '#DCF2E7', fontWeight: '700'},
  auditCard: {marginTop: 22, padding: 18, borderRadius: 20, backgroundColor: '#10252C', borderWidth: 1, borderColor: '#1D3A40'}, cardHeader: {flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center'}, cardLabel: {color: '#93ACAB', fontSize: 10, letterSpacing: 1.4, fontWeight: '800'}, status: {fontSize: 15, fontWeight: '800', marginTop: 5}, healthy: {color: '#72DDA2'}, danger: {color: '#FF7777'}, warning: {color: '#FFCB6B'}, score: {color: '#F3FBF5', fontSize: 30, fontWeight: '800'}, scoreUnit: {fontSize: 13, color: '#94ABAA'},
  metrics: {flexDirection: 'row', borderTopWidth: 1, borderBottomWidth: 1, borderColor: '#234047', marginTop: 18, paddingVertical: 15}, metric: {flex: 1}, metricValue: {color: '#F2F9F4', fontSize: 20, fontWeight: '800'}, metricLabel: {color: '#8FA5A7', fontSize: 9, fontWeight: '800', marginTop: 5, letterSpacing: 0.5}, traceButton: {flexDirection: 'row', justifyContent: 'space-between', paddingTop: 16}, traceTitle: {color: '#D9EBE0', fontWeight: '700'}, chevron: {color: '#72DDA2', fontSize: 20}, trace: {marginTop: 12, gap: 9}, traceLine: {color: '#A8BCB8', fontSize: 12, lineHeight: 18},
});

export default App;
