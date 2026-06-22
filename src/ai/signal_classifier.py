"""Local signal classifier — 5ms inference, no API calls.

Trained on successful AI parses from ai_format_candidates table.
Falls back to None when confidence < 0.85 (API takes over).
"""
import os
import re
import time
import pickle
import threading
from typing import Optional, Dict, Any


class LocalSignalClassifier:
    """On-device ML model for instant signal detection."""

    MODEL_DIR = os.path.join(os.path.dirname(__file__), 'models')
    MODEL_PATH = os.path.join(MODEL_DIR, 'signal_classifier.pkl')
    CONFIDENCE_THRESHOLD = 0.85
    MIN_TRAINING_SAMPLES = 20

    def __init__(self):
        self._vectorizer = None
        self._classifier = None
        self._entity_patterns = {}  # learned regex for symbol/strike/price extraction
        self._model_version = 0
        self._lock = threading.Lock()
        self._loaded = False
        self._load_model()

    def _load_model(self):
        """Load saved model from disk."""
        try:
            if os.path.exists(self.MODEL_PATH):
                with open(self.MODEL_PATH, 'rb') as f:
                    data = pickle.load(f)
                self._vectorizer = data.get('vectorizer')
                self._classifier = data.get('classifier')
                self._entity_patterns = data.get('entity_patterns', {})
                self._model_version = data.get('version', 0)
                self._loaded = True
                print(f'[AI_CLASSIFIER] ✓ Model loaded (v{self._model_version}, {len(self._entity_patterns)} entity patterns)')
        except Exception as e:
            print(f'[AI_CLASSIFIER] Model load error (will retrain): {e}')

    def predict(self, text: str) -> Optional[Dict[str, Any]]:
        """Classify signal text in <5ms. Returns None if not confident."""
        if not self._loaded or not self._classifier:
            return None
        try:
            start = time.monotonic()
            # Step 1: Binary classification — is this a trade signal?
            features = self._vectorizer.transform([text])
            proba = self._classifier.predict_proba(features)[0]
            is_signal_idx = list(self._classifier.classes_).index(1) if 1 in self._classifier.classes_ else -1
            if is_signal_idx < 0:
                return None
            confidence = proba[is_signal_idx]
            if confidence < self.CONFIDENCE_THRESHOLD:
                return None

            # Step 2: Entity extraction via learned patterns
            action = self._extract_action(text)
            symbol = self._extract_symbol(text)
            if not action or not symbol:
                return None

            price = self._extract_price(text)
            strike = self._extract_strike(text)
            option_type = self._extract_option_type(text)
            expiry = self._extract_expiry(text)
            is_conditional = self._detect_conditional(text)

            elapsed_ms = (time.monotonic() - start) * 1000
            result = {
                'action': action,
                'symbol': symbol.upper(),
                'price': price,
                'confidence': round(confidence, 3),
                '_local_model': True,
                '_model_version': self._model_version,
                '_inference_ms': round(elapsed_ms, 1),
            }
            if strike:
                result['strike'] = strike
                result['asset'] = 'option'
                result['asset_type'] = 'option'
            else:
                result['asset'] = 'stock'
                result['asset_type'] = 'stock'
            if option_type:
                result['option_type'] = option_type
            if expiry:
                result['expiry'] = expiry
            if is_conditional:
                result['is_conditional'] = True
                result['_conditional_order'] = True
                result['trigger_price'] = price
                result['trigger_type'] = 'over'
            return result
        except Exception as e:
            return None

    def _extract_action(self, text: str) -> Optional[str]:
        t = text.upper()
        # BTO patterns
        if re.search(r'\b(BTO|BUY TO OPEN|BUYING|LONG|GOING LONG|ENTERING)\b', t):
            return 'BTO'
        # STC patterns
        if re.search(r'\b(STC|SELL TO CLOSE|SOLD|SELLING|CLOSING|OUT|EXITING|TOOK PROFIT|CUT|TRIM|TRIMMING)\b', t):
            return 'STC'
        # Default: if has option/stock identifiers, assume BTO
        if re.search(r'\b\d+[CP]\b|\$[\d.]+', t):
            return 'BTO'
        return None

    def _extract_symbol(self, text: str) -> Optional[str]:
        t = text.upper().replace('$', '')
        # Match 1-5 letter symbols at word boundaries
        m = re.search(r'\b([A-Z]{1,5})\b(?=.*(?:\d+[CP]|@|\$|at |scalp|option|stock|call|put))', t)
        if m:
            sym = m.group(1)
            if sym not in ('BTO','STC','BUY','SELL','THE','FOR','AND','OUT','NOW','ALL','NEW','DAY','GTC'):
                return sym
        # Try $SYMBOL pattern
        m = re.search(r'\$([A-Z]{1,5})\b', text.upper())
        if m:
            return m.group(1)
        return None

    def _extract_price(self, text: str) -> Optional[float]:
        # Match @price, $price, at price
        m = re.search(r'[@$]\s*([\d]+\.?[\d]*)', text)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        m = re.search(r'\bat\s+([\d]+\.?[\d]*)', text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        return None

    def _extract_strike(self, text: str) -> Optional[float]:
        m = re.search(r'(\d+\.?\d*)\s*[CcPp]\b', text)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        return None

    def _extract_option_type(self, text: str) -> Optional[str]:
        m = re.search(r'\d+\.?\d*\s*([CcPp])\b', text)
        if m:
            return m.group(1).upper()
        if re.search(r'\b(CALL|CALLS)\b', text, re.IGNORECASE):
            return 'C'
        if re.search(r'\b(PUT|PUTS)\b', text, re.IGNORECASE):
            return 'P'
        return None

    def _extract_expiry(self, text: str) -> Optional[str]:
        m = re.search(r'(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?', text)
        if m:
            return m.group(0)
        return None

    def _detect_conditional(self, text: str) -> bool:
        return bool(re.search(r'\b(if it breaks|over|above|below|breaks?|trigger)\b', text, re.IGNORECASE))

    def train(self) -> dict:
        """Train/retrain from ai_format_candidates table."""
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import SGDClassifier
            from sklearn.model_selection import cross_val_score
            import numpy as np
        except ImportError:
            print('[AI_CLASSIFIER] scikit-learn not installed — skipping training')
            return {'error': 'scikit-learn not installed'}

        try:
            from gui_app.database import get_connection
            conn = get_connection()
            cursor = conn.cursor()

            # Positive samples: successful AI parses
            cursor.execute('''
                SELECT original_text FROM ai_format_candidates
                WHERE status IN ('approved', 'executed') AND ai_confidence >= 0.80
            ''')
            positives = [row[0] for row in cursor.fetchall()]

            # Negative samples: low confidence + dismissed
            cursor.execute('''
                SELECT original_text FROM ai_format_candidates
                WHERE status = 'dismissed' OR ai_confidence < 0.50
            ''')
            negatives = [row[0] for row in cursor.fetchall()]
            conn.close()

            # Need minimum samples
            if len(positives) < self.MIN_TRAINING_SAMPLES:
                return {'error': f'Need {self.MIN_TRAINING_SAMPLES} samples, have {len(positives)}'}

            # If not enough negatives, generate synthetic
            if len(negatives) < 10:
                negatives.extend([
                    'good morning everyone', 'lol nice trade', 'anyone in SPY?',
                    'market looking crazy today', 'gl everyone', 'nice call!',
                    'what do you think about AAPL?', 'im up 50% today',
                    'this channel is fire', 'thanks for the alerts',
                ])

            texts = positives + negatives
            labels = [1] * len(positives) + [0] * len(negatives)

            vectorizer = TfidfVectorizer(ngram_range=(1, 3), max_features=5000, lowercase=True)
            X = vectorizer.fit_transform(texts)

            classifier = SGDClassifier(loss='log_loss', max_iter=1000, random_state=42)
            classifier.fit(X, labels)

            # Cross-validation accuracy
            if len(texts) >= 10:
                scores = cross_val_score(classifier, X, labels, cv=min(5, len(texts)), scoring='accuracy')
                accuracy = float(np.mean(scores))
            else:
                accuracy = 0.0

            # Save model
            self._model_version += 1
            os.makedirs(self.MODEL_DIR, exist_ok=True)
            with open(self.MODEL_PATH, 'wb') as f:
                pickle.dump({
                    'vectorizer': vectorizer,
                    'classifier': classifier,
                    'entity_patterns': self._entity_patterns,
                    'version': self._model_version,
                }, f)

            with self._lock:
                self._vectorizer = vectorizer
                self._classifier = classifier
                self._loaded = True

            # Log training
            try:
                conn = get_connection()
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS ai_classifier_training_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        training_samples INTEGER,
                        accuracy REAL,
                        model_version INTEGER,
                        trained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                conn.execute('INSERT INTO ai_classifier_training_log (training_samples, accuracy, model_version) VALUES (?, ?, ?)',
                             (len(texts), accuracy, self._model_version))
                conn.commit()
                conn.close()
            except Exception:
                pass

            result = {'success': True, 'samples': len(texts), 'positives': len(positives),
                      'negatives': len(negatives), 'accuracy': accuracy, 'version': self._model_version}
            print(f'[AI_CLASSIFIER] ✓ Trained v{self._model_version}: {len(texts)} samples, accuracy={accuracy:.2%}')
            return result
        except Exception as e:
            print(f'[AI_CLASSIFIER] Training error: {e}')
            return {'error': str(e)}


# Singleton
_instance = None
def get_classifier() -> LocalSignalClassifier:
    global _instance
    if _instance is None:
        _instance = LocalSignalClassifier()
    return _instance
