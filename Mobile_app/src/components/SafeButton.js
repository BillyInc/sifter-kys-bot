import React, { useState, useRef } from 'react';
import { TouchableOpacity, Text, ActivityIndicator, View, StyleSheet } from 'react-native';

// Drop-in replacement for TouchableOpacity on any action that executes a trade
// or any other operation that must run exactly once.
const SafeButton = ({
  onPress,
  title,
  style,
  textStyle,
  loadingTitle = 'Processing...',
  debounceMs = 2000,
  requireConfirmation = false,
  confirmationTitle = 'Are you sure?',
  disabled = false,
  ...props
}) => {
  const [isProcessing, setIsProcessing] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const lastPressTime = useRef(0);

  const handlePress = async () => {
    const now = Date.now();

    // Debounce
    if (now - lastPressTime.current < debounceMs) return;

    // Already running
    if (isProcessing) return;

    // Require confirmation first press
    if (requireConfirmation && !showConfirm) {
      setShowConfirm(true);
      return;
    }

    setShowConfirm(false);
    lastPressTime.current = now;
    setIsProcessing(true);

    try {
      await Promise.race([
        onPress(),
        new Promise((_, reject) => setTimeout(() => reject(new Error('Timed out')), 30000))
      ]);
    } catch (err) {
      console.error('SafeButton error:', err.message);
    } finally {
      setIsProcessing(false);
    }
  };

  if (showConfirm) {
    return (
      <View style={styles.confirmContainer}>
        <Text style={styles.confirmTitle}>{confirmationTitle}</Text>
        <View style={styles.confirmRow}>
          <TouchableOpacity style={[styles.confirmBtn, styles.cancelBtn]} onPress={() => setShowConfirm(false)}>
            <Text style={styles.cancelText}>Cancel</Text>
          </TouchableOpacity>
          <TouchableOpacity style={[styles.confirmBtn, styles.yesBtn]} onPress={handlePress}>
            <Text style={styles.yesText}>Confirm</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  }

  return (
    <TouchableOpacity
      style={[styles.button, style, (isProcessing || disabled) && styles.disabled]}
      onPress={handlePress}
      disabled={isProcessing || disabled}
      activeOpacity={0.75}
      {...props}
    >
      {isProcessing
        ? <><ActivityIndicator color="white" style={{ marginRight: 8 }} /><Text style={[styles.text, textStyle]}>{loadingTitle}</Text></>
        : <Text style={[styles.text, textStyle]}>{title}</Text>
      }
    </TouchableOpacity>
  );
};

const styles = StyleSheet.create({
  button: { padding: 15, borderRadius: 10, alignItems: 'center', justifyContent: 'center', flexDirection: 'row' },
  disabled: { opacity: 0.5 },
  text: { color: 'white', fontWeight: '600', fontSize: 16 },
  confirmContainer: { padding: 16, backgroundColor: '#fff3cd', borderRadius: 10, borderWidth: 1, borderColor: '#ffc107' },
  confirmTitle: { fontSize: 15, fontWeight: '600', marginBottom: 12, textAlign: 'center' },
  confirmRow: { flexDirection: 'row', justifyContent: 'space-around' },
  confirmBtn: { paddingVertical: 10, paddingHorizontal: 28, borderRadius: 8 },
  cancelBtn: { backgroundColor: '#e5e7eb' },
  yesBtn: { backgroundColor: '#6366f1' },
  cancelText: { fontWeight: '600', color: '#333' },
  yesText: { fontWeight: '600', color: 'white' },
});

export default SafeButton;
