"""Voice stack — ASR (streaming_asr), TTS (text_to_speech), wake word, tone
classifier, speaker ID, and the conversation controller.

Declared a regular package (not a namespace) so imports resolve deterministically
even if another top-level `voice/` ever lands on sys.path.
"""
