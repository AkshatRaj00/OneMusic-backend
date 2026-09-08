import 'package:flutter/foundation.dart';
import 'package:just_audio/just_audio.dart';

import '../core/services/music_api_service.dart';
import '../models/song_model.dart';

class MusicPlayerProvider extends ChangeNotifier {
  final AudioPlayer _audioPlayer = AudioPlayer();

  List<SongModel> _songs = [];
  SongModel? _currentSong;
  bool _isLoading = false;
  bool _isSearching = false;
  String _error = '';

  List<SongModel> get songs => _songs;
  SongModel? get currentSong => _currentSong;
  bool get isLoading => _isLoading;
  bool get isSearching => _isSearching;
  String get error => _error;
  bool get isPlaying => _audioPlayer.playing;

  Future<void> loadTrending() async {
    _isLoading = true;
    _error = '';
    notifyListeners();

    try {
      _songs = await MusicApiService.instance.fetchTrendingSongs();
    } catch (e) {
      _error = e.toString();
      _songs = [];
    }

    _isLoading = false;
    notifyListeners();
  }

  Future<void> searchSongs(String query) async {
    _isSearching = true;
    _error = '';
    notifyListeners();

    try {
      _songs = await MusicApiService.instance.searchSongs(query);
    } catch (e) {
      _error = e.toString();
      _songs = [];
    }

    _isSearching = false;
    notifyListeners();
  }

  Future<void> playSong(SongModel song) async {
    _isLoading = true;
    _error = '';
    notifyListeners();

    try {
      await _audioPlayer.stop();

      final playable =
          await MusicApiService.instance.resolvePlayableSong(song);

      if (playable == null || playable.streamUrl.isEmpty) {
        throw Exception('Playable stream not found');
      }

      await _audioPlayer.setUrl(playable.streamUrl);
      await _audioPlayer.play();

      _currentSong = playable;
    } catch (e) {
      _error = e.toString();
    }

    _isLoading = false;
    notifyListeners();
  }

  Future<void> pause() async {
    await _audioPlayer.pause();
    notifyListeners();
  }

  Future<void> resume() async {
    await _audioPlayer.play();
    notifyListeners();
  }

  @override
  void dispose() {
    _audioPlayer.dispose();
    super.dispose();
  }
}