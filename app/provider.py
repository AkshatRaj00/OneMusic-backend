import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:just_audio/just_audio.dart';

import '../core/services/music_api_service.dart';
import '../models/song_model.dart';

class MusicPlayerProvider extends ChangeNotifier {
  final AudioPlayer _audioPlayer = AudioPlayer();

  StreamSubscription<PlayerState>? _playerStateSubscription;
  Timer? _debounceTimer;

  List<SongModel> _songs = [];
  SongModel? _currentSong;
  bool _isLoading = false;
  bool _isSearching = false;
  String _error = '';
  int _playRequestId = 0;

  MusicPlayerProvider() {
    _initPlayerListeners();
  }

  List<SongModel> get songs => List.unmodifiable(_songs);
  SongModel? get currentSong => _currentSong;
  bool get isLoading => _isLoading;
  bool get isSearching => _isSearching;
  String get error => _error;

  bool get isPlaying => _audioPlayer.playing;
  Duration get position => _audioPlayer.position;
  Duration? get duration => _audioPlayer.duration;

  Stream<Duration> get positionStream => _audioPlayer.positionStream;
  Stream<Duration?> get durationStream => _audioPlayer.durationStream;

  void _initPlayerListeners() {
    _playerStateSubscription = _audioPlayer.playerStateStream.listen(
      (state) {
        if (state.processingState == ProcessingState.completed) {
          _audioPlayer.seek(Duration.zero);
          _audioPlayer.pause();
        }

        notifyListeners();
      },
      onError: (Object error, StackTrace stackTrace) {
        debugPrint('[PLAYER STREAM ERROR] $error');
        debugPrintStack(stackTrace: stackTrace);

        _error = 'Playback error: $error';
        _isLoading = false;
        notifyListeners();
      },
    );
  }

  Future<void> loadTrending() async {
    _isLoading = true;
    _error = '';
    notifyListeners();

    try {
      _songs = await MusicApiService.instance.fetchTrendingSongs();
    } catch (error, stackTrace) {
      debugPrint('[TRENDING ERROR] $error');
      debugPrintStack(stackTrace: stackTrace);

      _songs = [];
      _error = 'Trending songs load nahi hue.';
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> searchSongs(String query) async {
    final cleanQuery = query.trim();

    _debounceTimer?.cancel();

    if (cleanQuery.isEmpty) {
      _songs = [];
      _error = '';
      _isSearching = false;
      notifyListeners();
      return;
    }

    _debounceTimer = Timer(
      const Duration(milliseconds: 500),
      () async {
        _isSearching = true;
        _error = '';
        notifyListeners();

        try {
          _songs = await MusicApiService.instance.searchSongs(cleanQuery);
        } catch (error, stackTrace) {
          debugPrint('[SEARCH ERROR] $error');
          debugPrintStack(stackTrace: stackTrace);

          _songs = [];
          _error = 'Search complete nahi hui.';
        } finally {
          _isSearching = false;
          notifyListeners();
        }
      },
    );
  }

  Future<void> playSong(SongModel song) async {
    final requestId = ++_playRequestId;

    _isLoading = true;
    _error = '';
    notifyListeners();

    try {
      await _audioPlayer.stop();

      final playable =
          await MusicApiService.instance.resolvePlayableSong(song);

      if (requestId != _playRequestId) {
        return;
      }

      if (playable == null || playable.streamUrl.trim().isEmpty) {
        throw Exception('Playable stream URL not resolved');
      }

      final streamUri = Uri.tryParse(playable.streamUrl.trim());

      if (streamUri == null ||
          !streamUri.hasScheme ||
          !['https', 'http'].contains(streamUri.scheme)) {
        throw Exception('Invalid audio stream URL');
      }

      await _audioPlayer.setAudioSource(
        AudioSource.uri(streamUri),
      );

      if (requestId != _playRequestId) {
        return;
      }

      _currentSong = playable;

      await _audioPlayer.play();
    } catch (error, stackTrace) {
      debugPrint('[PLAY ERROR] $error');
      debugPrintStack(stackTrace: stackTrace);

      if (requestId == _playRequestId) {
        _currentSong = null;
        _error = 'Playback failed: $error';
      }

      try {
        await _audioPlayer.stop();
      } catch (_) {}
    } finally {
      if (requestId == _playRequestId) {
        _isLoading = false;
        notifyListeners();
      }
    }
  }

  Future<void> pause() async {
    await _audioPlayer.pause();
    notifyListeners();
  }

  Future<void> resume() async {
    await _audioPlayer.play();
    notifyListeners();
  }

  Future<void> seek(Duration targetPosition) async {
    await _audioPlayer.seek(targetPosition);
  }

  @override
  void dispose() {
    _playRequestId++;
    _debounceTimer?.cancel();
    _playerStateSubscription?.cancel();
    _audioPlayer.dispose();
    super.dispose();
  }
}