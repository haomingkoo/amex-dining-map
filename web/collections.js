// Curated Collections and Blog Content

const COLLECTIONS = [
  {
    id: 'michelin-starred',
    title: '⭐ Michelin Star Dining',
    description: 'Fine dining experiences with Michelin recognition',
    icon: '⭐',
    filters: { michelin: true },
    highlight: 'Premium dining destination with international recognition'
  },
  {
    id: 'romantic-dinner',
    title: '💑 Romantic Dinner Spots',
    description: 'Perfect venues for special occasions and intimate dining',
    icon: '💑',
    filters: { ambiance: 'romantic' },
    highlight: 'Intimate atmosphere ideal for couples and celebrations'
  },
  {
    id: 'budget-friendly',
    title: '💰 Budget-Friendly Gems',
    description: 'Excellent value dining with quality cuisine',
    icon: '💰',
    filters: { priceRange: 'budget' },
    highlight: 'Quality dining without breaking the bank'
  },
  {
    id: 'tasting-menu',
    title: '🍽️ Tasting Menu Experiences',
    description: 'Chef\'s choice multi-course dining adventures',
    icon: '🍽️',
    filters: { tastingMenu: true },
    highlight: 'Curated culinary journey with multiple courses'
  },
  {
    id: 'hidden-gems',
    title: '🔍 Hidden Gems',
    description: 'Lesser-known dining destinations with exceptional quality',
    icon: '🔍',
    filters: { reviews: { min: 50, max: 500 } },
    highlight: 'Discovered by locals and connoisseurs'
  },
  {
    id: 'japanese-excellence',
    title: '🇯🇵 Japanese Excellence',
    description: 'Traditional and modern Japanese cuisine across Asia',
    icon: '🇯🇵',
    filters: { country: 'Japan', cuisine: ['Japanese', 'Sushi', 'Ramen'] },
    highlight: 'Authentic Japanese dining traditions'
  },
  {
    id: 'french-classics',
    title: '🇫🇷 French Classics',
    description: 'Traditional French cuisine and bistro experiences',
    icon: '🇫🇷',
    filters: { country: 'France', cuisine: 'French' },
    highlight: 'Iconic French culinary traditions'
  },
  {
    id: 'asian-fusion',
    title: '🌶️ Asian Fusion',
    description: 'Contemporary Asian cuisine blending traditions',
    icon: '🌶️',
    filters: { cuisine: ['Fusion', 'Pan-Asian'] },
    highlight: 'Modern interpretation of Asian flavors'
  }
];

const BLOG_POSTS = [
  {
    id: 'post-1',
    title: 'Ultimate Guide to Amex Platinum Dining Benefits',
    date: '2026-04-15',
    author: 'Platinum Concierge',
    category: 'Guide',
    excerpt: 'Unlock the full potential of your Amex Platinum dining benefits with this comprehensive guide.',
    content: `
      <p>Your American Express Platinum Card comes with exceptional dining benefits across the globe. This guide helps you maximize your dining credit and access exclusive restaurant partnerships.</p>

      <h3>Key Benefits</h3>
      <ul>
        <li><strong>$200 Annual Dining Credit:</strong> Use it at participating restaurants in the Amex Fine Dining Collection and worldwide partners</li>
        <li><strong>Elite Hotel Status:</strong> Gold status at most luxury hotel chains through our partnerships</li>
        <li><strong>Concierge Services:</strong> 24/7 access to our concierge for reservations and recommendations</li>
        <li><strong>Exclusive Events:</strong> Invitation-only dining experiences and culinary events</li>
      </ul>

      <h3>How to Maximize Your Credit</h3>
      <ol>
        <li>Explore the Interactive Map to find participating restaurants in your travel destinations</li>
        <li>Check restaurant details for specific program information and benefits</li>
        <li>Call our concierge for reservations and special requests</li>
        <li>Keep receipts to track your $200 annual dining credit usage</li>
      </ol>

      <p>Visit americanexpress.com for the most current list of benefits and participating establishments.</p>
    `
  },
  {
    id: 'post-2',
    title: 'Tokyo Dining: A Michelin-Starred Journey',
    date: '2026-04-10',
    author: 'Travel Correspondent',
    category: 'Destination Guide',
    excerpt: 'Explore Tokyo\'s world-renowned fine dining scene with exclusive Amex partnerships.',
    content: `
      <p>Tokyo is home to more Michelin-starred restaurants than any other city in the world. As an Amex Platinum member, you have access to many of these exceptional establishments.</p>

      <h3>The Michelin Star System</h3>
      <ul>
        <li><strong>⭐ One Star:</strong> "A very good restaurant in its category"</li>
        <li><strong>⭐⭐ Two Stars:</strong> "Excellent cuisine, worth a detour"</li>
        <li><strong>⭐⭐⭐ Three Stars:</strong> "Exceptional cuisine, worth a journey"</li>
      </ul>

      <h3>Neighborhoods to Explore</h3>
      <ul>
        <li><strong>Ginza:</strong> Traditional sushi and kaiseki restaurants</li>
        <li><strong>Shinjuku:</strong> Diverse dining with everything from ramen to fine dining</li>
        <li><strong>Roppongi:</strong> Modern cuisine and international restaurants</li>
        <li><strong>Asakusa:</strong> Traditional Japanese atmosphere with classic dishes</li>
      </ul>

      <h3>Dining Tips</h3>
      <p>Japanese restaurants often require reservations and have specific dress codes for fine dining establishments. Call ahead or use our concierge service for assistance with bookings.</p>
    `
  },
  {
    id: 'post-3',
    title: 'Hidden Gems: Budget-Friendly Fine Dining',
    date: '2026-04-05',
    author: 'Food Explorer',
    category: 'Tips & Tricks',
    excerpt: 'Discover exceptional dining without the premium price tag.',
    content: `
      <p>Great food doesn't always come with a high price tag. We've found some exceptional restaurants that offer outstanding cuisine at accessible price points.</p>

      <h3>Lunch vs. Dinner Pricing</h3>
      <p>Many fine dining restaurants offer significantly lower prices during lunch service. A meal that costs $150 per person at dinner might be $50 during lunch. Take advantage of this difference when planning your visits.</p>

      <h3>Off-Peak Dining</h3>
      <p>Dining on weekdays or earlier in the evening often means better availability and potentially lower prices. Plus, you'll experience a more relaxed atmosphere.</p>

      <h3>Tasting Menu Deals</h3>
      <p>While tasting menus seem expensive, they often provide excellent value by showcasing the chef's skill across multiple courses.</p>

      <h3>Using Your Dining Credit Wisely</h3>
      <p>Your $200 annual Amex Platinum dining credit stretches further at restaurants with lower check averages. This allows you to experience fine dining more frequently throughout the year.</p>
    `
  },
  {
    id: 'post-4',
    title: 'Singapore Love Dining: Culinary Excellence on the Island',
    date: '2026-03-28',
    author: 'Asia Correspondent',
    category: 'Destination Guide',
    excerpt: 'Discover Singapore\'s diverse dining landscape with exclusive Amex benefits.',
    content: `
      <p>Singapore is a melting pot of culinary traditions, where Chinese, Malay, Indian, and Western cuisines coexist and influence each other. Amex Platinum cardholders enjoy exclusive benefits at Love Dining partner restaurants.</p>

      <h3>What is Love Dining?</h3>
      <p>Love Dining is an exclusive program offering special privileges at carefully selected restaurants, including invitations to culinary events and exclusive menu items.</p>

      <h3>Must-Try Cuisines</h3>
      <ul>
        <li><strong>Hawker Centers:</strong> Street food at its finest, offering authentic local dishes</li>
        <li><strong>Chinese Fine Dining:</strong> Traditional and modern Cantonese cuisine</li>
        <li><strong>Peranakan Kitchen:</strong> Unique fusion of Chinese, Malay, and Indian influences</li>
        <li><strong>Contemporary Asian:</strong> Innovative takes on traditional dishes</li>
      </ul>

      <h3>Neighborhoods to Explore</h3>
      <p>From Chinatown's historic shophouses to Marina Bay's modern restaurants, Singapore offers dining diversity at every corner. Use our map to explore all available options.</p>
    `
  },
  {
    id: 'post-5',
    title: 'Vegetarian & Plant-Based Fine Dining',
    date: '2026-03-20',
    author: 'Culinary Specialist',
    category: 'Guide',
    excerpt: 'Exceptional plant-based dining experiences at Amex partner restaurants.',
    content: `
      <p>Plant-based cuisine is increasingly sophisticated at fine dining establishments. More restaurants than ever are offering creative vegetarian and vegan tasting menus.</p>

      <h3>What to Expect</h3>
      <ul>
        <li>Creative use of seasonal vegetables and sustainable ingredients</li>
        <li>Elevated preparation techniques equal to meat-focused cuisine</li>
        <li>Wine pairings designed for vegetarian courses</li>
        <li>Knowledgeable staff familiar with dietary requirements</li>
      </ul>

      <h3>Making Your Reservation</h3>
      <p>Always inform the restaurant of your dietary preferences when booking. Our concierge can help arrange special tasting menus tailored to your requirements.</p>

      <h3>Notable Destinations</h3>
      <p>Many Michelin-starred restaurants around the world now feature dedicated plant-based tasting menus. Check our interactive map for restaurants in your area with vegetarian options.</p>
    `
  }
];

function getCollectionInfo(collectionId) {
  return COLLECTIONS.find(c => c.id === collectionId);
}

function getBlogPost(postId) {
  return BLOG_POSTS.find(p => p.id === postId);
}

function searchBlogPosts(query) {
  const lower = query.toLowerCase();
  return BLOG_POSTS.filter(post =>
    post.title.toLowerCase().includes(lower) ||
    post.excerpt.toLowerCase().includes(lower) ||
    post.category.toLowerCase().includes(lower)
  );
}

function getPostsByCategory(category) {
  return BLOG_POSTS.filter(post => post.category === category);
}
