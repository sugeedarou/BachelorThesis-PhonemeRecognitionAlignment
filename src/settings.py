from pathlib import Path


TIMIT_PATH = Path('../data/timit')
DATA_PATH = Path('../data')
TRAIN_PATH = DATA_PATH / 'train'
CORE_TEST_PATH = DATA_PATH / 'core_test'
FULL_TEST_PATH = DATA_PATH / 'full_test'
VAL_PATH = DATA_PATH / 'val'

EXCLUDE_SA_FILES  = True
AUGMENT_DATASET   = True
USE_FULL_TEST_SET = False
VAL_PERCENTAGE = 0.05
FRAME_LENGTH = 25  # in ms
STRIDE = 10  # in ms
N_MELS = 80
SAMPLE_RATE = 16000

# semi-constants (depend on previous constants)
SAMPLES_PER_FRAME = (SAMPLE_RATE // 1000) * FRAME_LENGTH
SAMPLES_PER_STRIDE = (SAMPLE_RATE // 1000) * STRIDE